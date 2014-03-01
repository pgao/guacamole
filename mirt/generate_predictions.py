"""Loads a json mirt file and a test file with assessments to evaluate.
   Outputs a series of tuples of predictions and actual responses.
"""
import json
import numpy
import random

import mirt.engine
import mirt.mirt_engine
from train_util.model_training_util import FieldIndexer


def load_and_simulate_assessment(
        json_filepath, roc_filepath, test_filepath, data_format='simple',
        evaluation_item_index=None):
    """Loads a json mirt file and a test file with assessments to evaluate.

    Some questions are marked as evaluation items, and these items are held
    out from training the model they are associated with, and instead are
    used to evaluate the model for accuracy, by training the model with all
    non-evaluation items, and then recording those predictions.

    Those predictions and the ground truth are written to the file
    at roc_file, and used to evaluate the accuracy of the algorithm, likely
    with a ROC curve.

    Arguments:
        json_filepath: The complete filepath the the mirt file. This is the
            format that is generated by mirt_npz_to_json.py. This file will be
            read.
        roc_filepath: The complete filepath to the file we will predictions to.
            This file will be written in a format parseable by
            plot_roc_curves.py (in particular, <response,prediction> where
            response is 0 or 1 depending on accuracy, and prediction is the
            prediction output by the model.)
        test_filepath: The file containing test data. This is going to be comma
            separated values with arguments specified by the optional arguments
            to load_and_simulate_assessment.

        The index arguments refer to the index within the test data at which
        various values are located

        user_index: The index at which the user id lives. This user id is used
            to detect when one assessment ends and the next begins.
        exercise_index: The index at which the exercise id lives. This index is
            used to store the slug of the exercise, which should be the same
            here as it is in the json model.
        time_index: The index at which the amount of time taken to solve the
            problem in seconds is stored.
        correct_index: The index at which whether the student answered
            correctly or not is stored. When true, this value should be stored
            as 'True' or 'true' (without the quotes.)
        evaluation_item_index: The index of the flag used to indicate whether
            this response should be used to generate the ROC curve.
            If the response should be held out, this value should be 'true' or
            'True'.  If there is no such value, keep a random item.
    """
    # Load the parameters from the json parameter file.
    with open(json_filepath, 'r') as json_file:
        params = json.load(json_file)['params']
        params['theta_flat'] = numpy.array(params['theta_flat'])

    # Load the indexer for the data
    indexer = FieldIndexer.get_for_slug(data_format)

    datapoints = []

    # Iterate through each user's data, writing out a datapoint for
    # each user.
    with open(roc_filepath, 'w') as outfile, \
            open(test_filepath, 'r') as test_data:

        user = ''
        model = mirt.mirt_engine.MIRTEngine(params)
        history = []
        evaluation_indexes = []
        model.only_live_exercises = False

        for line in test_data:
            # Read in the next line
            new_user, ex, time, correct, is_evaluation = parse_line(
                line, indexer, evaluation_item_index)

            # When we see a new user reset the model and calculate predictions.
            if user != new_user:
                # Generate the datapoint for the existing user history
                if user:
                    datapoints.extend(
                        write_roc_datapoint(
                            history, evaluation_indexes, model, outfile))

                # Reset all of the variables.
                user = new_user
                model = mirt.mirt_engine.MIRTEngine(params)
                history = []
                evaluation_indexes = []

            # Finally, append the response to the history
            response = mirt.engine.ItemResponse.new(
                correct=correct, exercise=ex, time_taken=time)
            history.append(response.data)

            # Save the indexes of the evaluation items for use when generating
            # points for the ROC curve.
            if is_evaluation:
                evaluation_indexes.append(len(history) - 1)
        test_data.close()
        outfile.close()
    return datapoints


def parse_line(line, indexer, evaluation_item_index):
    """Parses a line of an input file in a specified format.

    Takes a line and the location of various critical fields within the line

    Returns the user, exercise, time taken, and whether the problem was
    answered correctly
    """
    line = line.strip().split(',')
    user = line[indexer.user]
    ex = line[indexer.exercise]
    time = line[indexer.time_taken]
    correct = line[indexer.correct] in ('true', 'True', 1)
    if evaluation_item_index is not None:
        is_evaluation = line[evaluation_item_index] in ('true', 'True')
    else:
        is_evaluation = False
    return user, ex, time, correct, is_evaluation


def write_roc_datapoint(history, evaluation_indexes, model, outfile):
    """Writes the actual and predicted accuracy for a user on a problem

    Arguments:
        history: A list of item responses given by a single user.
        evaluation_item_index: The index in the list at which the item we
            hold out and generate an ROC datapoint for is located.
            If there is no such index, write a random item
        model: a model that holds the trained parameters and makes predictions
            about accuracy.
        outfile: An open file we print the roc point to.

    Prints datapoints in the format 1,.73 representing whether the student
    answered the question correctly, and how likely our model thought it was
    that they give the response they gave.
    """
    # First we reverse the order of the evaluation indexes, so that as we
    # remove these holdout exercises, the index positions do not change.
    evaluation_indexes.reverse()

    # If there is no evaluation index, evaluate a random response
    if not evaluation_indexes:
        evaluation_indexes = [random.choice(range(len(history)))]

    # We collect all evaluation items in a list and remove them from history
    # so that we can evaluate the models accuracy untainted with information
    # about the evaluation items.
    evaluation_items = []
    for evaluation_item_index in evaluation_indexes:
        # remove the evaluation item from the model's history and save it
        evaluation_items.append(history.pop(evaluation_item_index))
        # Get the prediction by the model for the saved evaluation item given
        # the history
    roc_points = []
    # For each of the collected evaluation items, write the predicted accuracy
    for evaluation_item in evaluation_items:
        acc = model.estimated_exercise_accuracy(
            history, evaluation_item['exercise'])

        # Finally, write the actual accuracy of the student on the exercise,
        # followed by the predicted accuracy.
        roc_point = []
        if evaluation_item['correct']:
            roc_point.append(1)
        else:
            roc_point.append(0)
        roc_point.append(acc)
        roc_points.append(roc_point)
    return roc_points
