import os
import logging
import jsonpickle
import boto3
from botocore.exceptions import ClientError
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all
import tarfile
from io import BytesIO
from io import StringIO
import json
import taskfile
import taskmessage
import dotvfile
import csvfile
import issuetable


logger = logging.getLogger()
logger.setLevel(logging.INFO)
patch_all()


def preamble(event, context):
    logger.info('## ENVIRONMENT VARIABLES\r' + jsonpickle.encode(dict(**os.environ)))
    logger.info('## EVENT\r' + jsonpickle.encode(event))
    logger.info('## CONTEXT\r' + jsonpickle.encode(context))
    client = boto3.client('lambda')
    account_settings = client.get_account_settings()
    print(account_settings['AccountUsage'])
    return True


def get_env_var(env_var_name):
    env_var = ''
    if env_var_name in os.environ:
        env_var = os.environ[env_var_name]
    else:
        print(f'get_env_var: Failed to get {env_var_name}.')
    return env_var


def get_env_vars():
    global result_bucket_name
    global generate_task_summary_queue_name

    result_bucket_name = get_env_var('RESULT_DATA_BUCKET')
    if result_bucket_name == '':
        return False

    generate_task_summary_queue_name = get_env_var('GENERATE_TASK_SUMMARY_QUEUE')
    if generate_task_summary_queue_name == '':
        return False

    # success
    return True


def parse_event_record(event_record):
    global task

    event_body = eval(event_record['body'])
    if event_body is None:
        print('parse_event: event body is missing.')
        return False

    task = event_body['task']
    if task is None:
        print('parse_event: task is missing.')
        return False

    # success
    return True


def write_issue_record(issue_table, issue):
    # create issue record
    issue_record = issuetable.create_issue_record(issue_table, issue)
    if issue_record is None:
        print('write_issue_record: create_issue_record failed.')
        return False

    # debug: get and print issue record
    task_id = issue_record['task_id']
    task_issue_number = issue_record['task_issue_number']
    issue_record = issuetable.get_issue_record(issue_table, task_id, task_issue_number)
    if issue_record is None:
        print('write_issue_record: get_issue_record failed.')
        return False

    print('Issue record:')
    print(issue_record)

    return True


def write_task_issues(task, scan_result_tar_content, slash_tmp_csv_file_name, issue_table):
    # initialize task_id and task issue number
    task_id = task['task_id']
    task_issue_number = 1
    print(f'write_task_issues: Starting task issue number is {task_issue_number}.')

    # foreach dot v file, decode and write task issues to csv file and issue table
    with tarfile.open(fileobj = BytesIO(scan_result_tar_content)) as tar:
        for tar_resource in tar:
            if (tar_resource.isfile()):
                # extract dot v file blob from tar resource
                dot_v_file_bytes = tar.extractfile(tar_resource).read()
                if dot_v_file_bytes is None:
                    print('write_task_issues: Empty .v file.  Next.')
                    continue

                # load convert dot v file blob to a json object
                dot_v_file_json = json.loads(dot_v_file_bytes)
                if dot_v_file_json is None:
                    print('write_task_issues: Null JSON object.  Next.')
                    continue

                # decode dot v file issues
                task_issues = dotvfile.decode_dot_v_file_issues(task_id, task_issue_number, dot_v_file_json)
                if task_issues is None:
                    print('write_task_issues: decode_dot_v_file_issues failed.  Next.')
                    continue

                # write to csv file
                success = csvfile.append_task_issues_csv_rows(slash_tmp_csv_file_name, task_issues)
                if not success:
                    print('write_task_issues: append_task_issues_csv_rows failed.  Next.')
                    continue

                # write to issue table
                for task_issue in task_issues:
                    success = write_issue_record(issue_table, task_issue)
                    if not success:
                        print('write_task_issues: write_issue_record failed.  Next.')
                        continue

                # success: update task issue number
                num_task_issues = len(task_issues)
                task_issue_number += num_task_issues
                print(f'write_task_issues: Wrote {num_task_issues} issues.')
                print(f'write_task_issues: Next task issue number is {task_issue_number}.')

    # success
    return True


# uploadTaskIssues handler
def uploadTaskIssues(event, context):
    success = preamble(event, context)
    if not success:
        print('preamble failed. Exit.')
        return False

    # get env vars
    success = get_env_vars()
    if not success:
        print('get_env_vars failed.  Exit.')
        return False

    print('Env vars:')
    print(f'result_bucket_name: {result_bucket_name}')
    print(f'generate_task_summary_queue_name: {generate_task_summary_queue_name}')

    # get issue table
    issue_table = issuetable.get_issue_table()
    if issue_table is None:
        print('get_issue_table failed.  Exit.')
        return False

    # get and write task issue records
    event_records = event['Records']
    for event_record in event_records:
        # debug: print event record
        print('Event record:')
        print(event_record)

        # parse event record
        success = parse_event_record(event_record)
        if not success:
            print('parse_event_record failed.  Exit.')
            continue

        # debug: print event record attributes
        print('Event record attributes:')
        print(f'task: {task}')

        # get scan result tar blob in memory (max 3 GB)
        task_file_attribute_name = 'task_scan_result_tar'
        task[task_file_attribute_name] = 'scan_result.tar.gz'
        scan_result_tar_blob = taskfile.get_task_file_blob(result_bucket_name, task, task_file_attribute_name)
        if scan_result_tar_blob is None:
            print('get_task_file_blob failed.  Next.')
            continue

        # write /tmp/$(task_id)_issues.csv file header
        user_id = task['user_id']
        task_id = task['task_id']
        csv_file_name = task_id + '_issues.csv'
        slash_tmp_csv_file_name = '/tmp/' + csv_file_name
        success = csvfile.write_task_issues_csv_header(slash_tmp_csv_file_name)
        if not success:
            print('write_task_issues: write_task_issues_csv_header failed.  Exit.')
            continue

        # extract dot v files and write task issues
        success = write_task_issues(task, scan_result_tar_blob, slash_tmp_csv_file_name, issue_table)
        if not success:
            print('write_task_issues failed.  Next.')
            continue

        # upload /tmp/$(task_id)_issues.csv to result data bucket
        success = taskfile.upload_file_from_slash_tmp(result_bucket_name, user_id, task_id, csv_file_name)
        if not success:
            print(f'upload_file_from_slash_tmp failed: {csv_file_name}.  Next.')
            continue

        # send task context to update task log stream queue
        action = 'generate_task_summary'
        success = taskmessage.send_task_message(generate_task_summary_queue_name, action, task)
        if not success:
            print('send_message failed.  Next.')
            continue

    # success
    return True


# main function for testing updateTask handler
def main():
    xray_recorder.begin_segment('main_function')
    file = open('event.json', 'rb')
    try:
        # read sample event
        ba = bytearray(file.read())
        event = jsonpickle.decode(ba)
        logger.warning('## EVENT')
        logger.warning(jsonpickle.encode(event))
        # create sample context
        context = {'requestid': '1234'}
        # invoke handler
        result = uploadTaskIssues(event, context)
        # print response
        print('## RESPONSE')
        print(str(result))
    finally:
        file.close()
    file.close()
    xray_recorder.end_segment()


if __name__ == '__main__':
    main()

