#!/bin/bash
declare -a vars=(AWS_ACCOUNT_ID \
  TARGET_REGION \
  TASK_EXEC_PREPROCESS_DATA_BUCKET \
  TASK_EXEC_LOG_DATA_BUCKET \
  TASK_EXEC_RESULT_DATA_BUCKET \
  TASK_EXEC_CREATE_TASK_QUEUE \
  TASK_EXEC_PROCESS_TASK_QUEUE \
  TASK_EXEC_UPDATE_TASK_QUEUE \
  TASK_EXEC_UPLOAD_TASK_ISSUES_QUEUE \
  TASK_EXEC_GENERATE_TASK_SUMMARY_QUEUE \
  TASK_EXEC_TASK_TABLE \
  TASK_EXEC_ISSUE_TABLE \
  TASK_LIST_APPS_BUCKET \
  TASK_LIST_DOMAIN)

for var_name in "${vars[@]}"
do
  if [ -z "$(eval "echo \$$var_name")" ]; then
    echo "Missing environment variable $var_name. Please set before continuing"
    exit 1
  fi
done

