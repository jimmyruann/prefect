from __future__ import annotations

import copy
import json
import os
import textwrap
import warnings
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Generator

import pydantic
import pytest
import toml
from pydantic_core import to_jsonable_python
from sqlalchemy import make_url

import prefect.context
import prefect.settings
from prefect.exceptions import ProfileSettingsValidationError
from prefect.settings import (
    PREFECT_API_DATABASE_DRIVER,
    PREFECT_API_DATABASE_HOST,
    PREFECT_API_DATABASE_NAME,
    PREFECT_API_DATABASE_PASSWORD,
    PREFECT_API_DATABASE_PORT,
    PREFECT_API_DATABASE_USER,
    PREFECT_API_KEY,
    PREFECT_API_URL,
    PREFECT_CLIENT_CUSTOM_HEADERS,
    PREFECT_CLIENT_RETRY_EXTRA_CODES,
    PREFECT_CLOUD_API_URL,
    PREFECT_CLOUD_UI_URL,
    PREFECT_DEBUG_MODE,
    PREFECT_HOME,
    PREFECT_LOGGING_EXTRA_LOGGERS,
    PREFECT_LOGGING_LEVEL,
    PREFECT_LOGGING_SERVER_LEVEL,
    PREFECT_PROFILES_PATH,
    PREFECT_SERVER_ALLOW_EPHEMERAL_MODE,
    PREFECT_SERVER_API_HOST,
    PREFECT_SERVER_API_PORT,
    PREFECT_SERVER_DATABASE_CONNECTION_URL,
    PREFECT_SERVER_LOGGING_LEVEL,
    PREFECT_TASK_DEFAULT_RETRY_DELAY_SECONDS,
    PREFECT_TEST_MODE,
    PREFECT_TEST_SETTING,
    PREFECT_UI_API_URL,
    PREFECT_UI_URL,
    PREFECT_UNIT_TEST_MODE,
    Profile,
    ProfilesCollection,
    Settings,
    get_current_settings,
    load_profile,
    load_profiles,
    save_profiles,
    temporary_settings,
)
from prefect.settings.base import _to_environment_variable_value
from prefect.settings.constants import DEFAULT_PROFILES_PATH
from prefect.settings.legacy import (
    Setting,
    _env_var_to_accessor,
    _get_settings_fields,
    _get_valid_setting_names,
)
from prefect.settings.models.api import APISettings
from prefect.settings.models.client import ClientSettings
from prefect.settings.models.logging import LoggingSettings
from prefect.settings.models.results import ResultsSettings
from prefect.settings.models.server import ServerSettings
from prefect.settings.models.server.api import ServerAPISettings
from prefect.settings.models.server.database import (
    ServerDatabaseSettings,
    SQLAlchemySettings,
)
from prefect.utilities.collections import get_from_dict, set_in_dict
from prefect.utilities.filesystem import tmpchdir

SUPPORTED_SETTINGS = {
    "PREFECT_API_AUTH_STRING": {"test_value": "admin:admin"},
    "PREFECT_API_BLOCKS_REGISTER_ON_START": {"test_value": True, "legacy": True},
    "PREFECT_API_DATABASE_CONNECTION_TIMEOUT": {"test_value": 10.0, "legacy": True},
    "PREFECT_API_DATABASE_CONNECTION_URL": {"test_value": "sqlite:///", "legacy": True},
    "PREFECT_API_DATABASE_DRIVER": {"test_value": "sqlite+aiosqlite", "legacy": True},
    "PREFECT_API_DATABASE_ECHO": {"test_value": True, "legacy": True},
    "PREFECT_API_DATABASE_HOST": {"test_value": "localhost", "legacy": True},
    "PREFECT_API_DATABASE_MIGRATE_ON_START": {"test_value": True, "legacy": True},
    "PREFECT_API_DATABASE_NAME": {"test_value": "prefect", "legacy": True},
    "PREFECT_API_DATABASE_PASSWORD": {"test_value": "password", "legacy": True},
    "PREFECT_API_DATABASE_PORT": {"test_value": 5432, "legacy": True},
    "PREFECT_API_DATABASE_TIMEOUT": {"test_value": 10.0, "legacy": True},
    "PREFECT_API_DATABASE_USER": {"test_value": "user", "legacy": True},
    "PREFECT_API_DEFAULT_LIMIT": {"test_value": 100, "legacy": True},
    "PREFECT_API_ENABLE_HTTP2": {"test_value": True},
    "PREFECT_API_ENABLE_METRICS": {"test_value": True, "legacy": True},
    "PREFECT_API_EVENTS_RELATED_RESOURCE_CACHE_TTL": {
        "test_value": timedelta(minutes=6),
        "legacy": True,
    },
    "PREFECT_API_EVENTS_STREAM_OUT_ENABLED": {"test_value": True, "legacy": True},
    "PREFECT_API_KEY": {"test_value": "key"},
    "PREFECT_API_LOG_RETRYABLE_ERRORS": {"test_value": True, "legacy": True},
    "PREFECT_API_MAX_FLOW_RUN_GRAPH_ARTIFACTS": {"test_value": 10, "legacy": True},
    "PREFECT_API_MAX_FLOW_RUN_GRAPH_NODES": {"test_value": 100, "legacy": True},
    "PREFECT_API_REQUEST_TIMEOUT": {"test_value": 10.0},
    "PREFECT_API_SERVICES_CANCELLATION_CLEANUP_ENABLED": {
        "test_value": True,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_CANCELLATION_CLEANUP_LOOP_SECONDS": {
        "test_value": 10.0,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_EVENT_LOGGER_ENABLED": {
        "test_value": True,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_EVENT_PERSISTER_BATCH_SIZE": {
        "test_value": 100,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_EVENT_PERSISTER_ENABLED": {
        "test_value": True,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_EVENT_PERSISTER_FLUSH_INTERVAL": {
        "test_value": 10.0,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_FOREMAN_DEPLOYMENT_LAST_POLLED_TIMEOUT_SECONDS": {
        "test_value": 10,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_FOREMAN_ENABLED": {"test_value": True, "legacy": True},
    "PREFECT_API_SERVICES_FOREMAN_FALLBACK_HEARTBEAT_INTERVAL_SECONDS": {
        "test_value": 10,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_FOREMAN_INACTIVITY_HEARTBEAT_MULTIPLE": {
        "test_value": 2,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_FOREMAN_LOOP_SECONDS": {"test_value": 10.0, "legacy": True},
    "PREFECT_API_SERVICES_FOREMAN_WORK_QUEUE_LAST_POLLED_TIMEOUT_SECONDS": {
        "test_value": 10,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_LATE_RUNS_AFTER_SECONDS": {
        "test_value": timedelta(seconds=20),
        "legacy": True,
    },
    "PREFECT_API_SERVICES_LATE_RUNS_ENABLED": {"test_value": True, "legacy": True},
    "PREFECT_API_SERVICES_LATE_RUNS_LOOP_SECONDS": {"test_value": 10.0, "legacy": True},
    "PREFECT_API_SERVICES_PAUSE_EXPIRATIONS_ENABLED": {
        "test_value": True,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_PAUSE_EXPIRATIONS_LOOP_SECONDS": {
        "test_value": 10.0,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_SCHEDULER_DEPLOYMENT_BATCH_SIZE": {
        "test_value": 10,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_SCHEDULER_ENABLED": {"test_value": True, "legacy": True},
    "PREFECT_API_SERVICES_SCHEDULER_INSERT_BATCH_SIZE": {
        "test_value": 10,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_SCHEDULER_LOOP_SECONDS": {
        "test_value": 10.0,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_SCHEDULER_MAX_RUNS": {"test_value": 10, "legacy": True},
    "PREFECT_API_SERVICES_SCHEDULER_MAX_SCHEDULED_TIME": {
        "test_value": timedelta(hours=10),
        "legacy": True,
    },
    "PREFECT_API_SERVICES_SCHEDULER_MIN_RUNS": {"test_value": 10, "legacy": True},
    "PREFECT_API_SERVICES_SCHEDULER_MIN_SCHEDULED_TIME": {
        "test_value": timedelta(minutes=10),
        "legacy": True,
    },
    "PREFECT_API_SERVICES_TASK_RUN_RECORDER_ENABLED": {
        "test_value": True,
        "legacy": True,
    },
    "PREFECT_API_SERVICES_TRIGGERS_ENABLED": {"test_value": True, "legacy": True},
    "PREFECT_API_SSL_CERT_FILE": {"test_value": "/path/to/cert"},
    "PREFECT_API_TASK_CACHE_KEY_MAX_LENGTH": {"test_value": 10, "legacy": True},
    "PREFECT_API_TLS_INSECURE_SKIP_VERIFY": {"test_value": True},
    "PREFECT_API_URL": {"test_value": "https://api.prefect.io"},
    "PREFECT_CLIENT_CSRF_SUPPORT_ENABLED": {"test_value": True},
    "PREFECT_CLIENT_CUSTOM_HEADERS": {"test_value": '{"X-CUSTOM": "foobar"}'},
    "PREFECT_CLIENT_ENABLE_METRICS": {"test_value": True, "legacy": True},
    "PREFECT_CLIENT_MAX_RETRIES": {"test_value": 3},
    "PREFECT_CLIENT_METRICS_ENABLED": {
        "test_value": True,
    },
    "PREFECT_CLIENT_METRICS_PORT": {"test_value": 9000},
    "PREFECT_CLIENT_RETRY_EXTRA_CODES": {"test_value": {400, 300}},
    "PREFECT_CLIENT_RETRY_JITTER_FACTOR": {"test_value": 0.5},
    "PREFECT_CLI_COLORS": {"test_value": True},
    "PREFECT_CLI_PROMPT": {"test_value": True},
    "PREFECT_CLI_WRAP_LINES": {"test_value": True},
    "PREFECT_CLOUD_API_URL": {"test_value": "https://cloud.prefect.io"},
    "PREFECT_CLOUD_ENABLE_ORCHESTRATION_TELEMETRY": {"test_value": True},
    "PREFECT_CLOUD_UI_URL": {"test_value": "https://cloud.prefect.io"},
    "PREFECT_DEBUG_MODE": {"test_value": True},
    "PREFECT_DEFAULT_DOCKER_BUILD_NAMESPACE": {"test_value": "prefect", "legacy": True},
    "PREFECT_DEFAULT_RESULT_STORAGE_BLOCK": {"test_value": "block", "legacy": True},
    "PREFECT_DEFAULT_WORK_POOL_NAME": {"test_value": "default", "legacy": True},
    "PREFECT_DEPLOYMENT_CONCURRENCY_SLOT_WAIT_SECONDS": {
        "test_value": 10.0,
        "legacy": True,
    },
    "PREFECT_DEPLOYMENT_SCHEDULE_MAX_SCHEDULED_RUNS": {
        "test_value": 10,
        "legacy": True,
    },
    "PREFECT_DEPLOYMENTS_DEFAULT_DOCKER_BUILD_NAMESPACE": {"test_value": "prefect"},
    "PREFECT_DEPLOYMENTS_DEFAULT_WORK_POOL_NAME": {"test_value": "default"},
    "PREFECT_EVENTS_EXPIRED_BUCKET_BUFFER": {
        "test_value": timedelta(seconds=60),
        "legacy": True,
    },
    "PREFECT_EVENTS_MAXIMUM_LABELS_PER_RESOURCE": {"test_value": 10, "legacy": True},
    "PREFECT_EVENTS_MAXIMUM_RELATED_RESOURCES": {"test_value": 10, "legacy": True},
    "PREFECT_EVENTS_MAXIMUM_SIZE_BYTES": {"test_value": 10, "legacy": True},
    "PREFECT_EVENTS_MAXIMUM_WEBSOCKET_BACKFILL": {
        "test_value": timedelta(minutes=15),
        "legacy": True,
    },
    "PREFECT_EVENTS_PROACTIVE_GRANULARITY": {
        "test_value": timedelta(seconds=5),
        "legacy": True,
    },
    "PREFECT_EVENTS_RETENTION_PERIOD": {
        "test_value": timedelta(hours=7),
        "legacy": True,
    },
    "PREFECT_EVENTS_WEBSOCKET_BACKFILL_PAGE_SIZE": {"test_value": 10, "legacy": True},
    "PREFECT_EXPERIMENTAL_WARN": {"test_value": True, "legacy": True},
    "PREFECT_EXPERIMENTS_WARN": {"test_value": True},
    "PREFECT_EXPERIMENTS_LINEAGE_EVENTS_ENABLED": {"test_value": True},
    "PREFECT_FLOW_DEFAULT_RETRIES": {"test_value": 10, "legacy": True},
    "PREFECT_FLOWS_DEFAULT_RETRIES": {"test_value": 10},
    "PREFECT_FLOW_DEFAULT_RETRY_DELAY_SECONDS": {"test_value": 10, "legacy": True},
    "PREFECT_FLOWS_DEFAULT_RETRY_DELAY_SECONDS": {"test_value": 10},
    "PREFECT_HOME": {"test_value": Path.home() / ".prefect" / "test"},
    "PREFECT_INTERNAL_LOGGING_LEVEL": {"test_value": "INFO"},
    "PREFECT_LOCAL_STORAGE_PATH": {
        "test_value": Path("/path/to/storage"),
        "legacy": True,
    },
    "PREFECT_LOGGING_COLORS": {"test_value": True},
    "PREFECT_LOGGING_CONFIG_PATH": {"test_value": Path("/path/to/settings.yaml")},
    "PREFECT_LOGGING_EXTRA_LOGGERS": {"test_value": ["foo", "bar"]},
    "PREFECT_LOGGING_INTERNAL_LEVEL": {"test_value": "INFO", "legacy": True},
    "PREFECT_LOGGING_LEVEL": {"test_value": "INFO"},
    "PREFECT_LOGGING_LOG_PRINTS": {"test_value": True},
    "PREFECT_LOGGING_MARKUP": {"test_value": True},
    "PREFECT_LOGGING_SERVER_LEVEL": {"test_value": "INFO", "legacy": True},
    "PREFECT_LOGGING_SETTINGS_PATH": {
        "test_value": Path("/path/to/settings.toml"),
        "legacy": True,
    },
    "PREFECT_LOGGING_TO_API_BATCH_INTERVAL": {"test_value": 10.0},
    "PREFECT_LOGGING_TO_API_BATCH_SIZE": {"test_value": 5_000_000},
    "PREFECT_LOGGING_TO_API_ENABLED": {"test_value": True},
    "PREFECT_LOGGING_TO_API_MAX_LOG_SIZE": {"test_value": 10},
    "PREFECT_LOGGING_TO_API_WHEN_MISSING_FLOW": {"test_value": "ignore"},
    "PREFECT_MEMOIZE_BLOCK_AUTO_REGISTRATION": {"test_value": True, "legacy": True},
    "PREFECT_MEMO_STORE_PATH": {"test_value": Path("/path/to/memo"), "legacy": True},
    "PREFECT_MESSAGING_BROKER": {"test_value": "broker", "legacy": True},
    "PREFECT_MESSAGING_CACHE": {"test_value": "cache", "legacy": True},
    "PREFECT_PROFILES_PATH": {"test_value": Path("/path/to/profiles.toml")},
    "PREFECT_RESULTS_DEFAULT_SERIALIZER": {"test_value": "serializer"},
    "PREFECT_RESULTS_DEFAULT_STORAGE_BLOCK": {"test_value": "block"},
    "PREFECT_RESULTS_LOCAL_STORAGE_PATH": {"test_value": Path("/path/to/storage")},
    "PREFECT_RESULTS_PERSIST_BY_DEFAULT": {"test_value": True},
    "PREFECT_RUNNER_HEARTBEAT_FREQUENCY": {"test_value": 30},
    "PREFECT_RUNNER_POLL_FREQUENCY": {"test_value": 10},
    "PREFECT_RUNNER_PROCESS_LIMIT": {"test_value": 10},
    "PREFECT_RUNNER_SERVER_ENABLE": {"test_value": True},
    "PREFECT_RUNNER_SERVER_HOST": {"test_value": "host"},
    "PREFECT_RUNNER_SERVER_LOG_LEVEL": {"test_value": "INFO"},
    "PREFECT_RUNNER_SERVER_MISSED_POLLS_TOLERANCE": {"test_value": 10},
    "PREFECT_RUNNER_SERVER_PORT": {"test_value": 8080},
    "PREFECT_SERVER_ALLOW_EPHEMERAL_MODE": {"test_value": True, "legacy": True},
    "PREFECT_SERVER_API_AUTH_STRING": {"test_value": "admin:admin"},
    "PREFECT_SERVER_API_BASE_PATH": {"test_value": "/v2/api"},
    "PREFECT_SERVER_ANALYTICS_ENABLED": {"test_value": True},
    "PREFECT_SERVER_API_CORS_ALLOWED_HEADERS": {"test_value": "foo"},
    "PREFECT_SERVER_API_CORS_ALLOWED_METHODS": {"test_value": "foo"},
    "PREFECT_SERVER_API_CORS_ALLOWED_ORIGINS": {"test_value": "foo"},
    "PREFECT_SERVER_API_CSRF_TOKEN_EXPIRATION": {"test_value": timedelta(seconds=10)},
    "PREFECT_SERVER_API_CSRF_PROTECTION_ENABLED": {"test_value": True},
    "PREFECT_SERVER_API_DEFAULT_LIMIT": {"test_value": 10},
    "PREFECT_SERVER_API_HOST": {"test_value": "host"},
    "PREFECT_SERVER_API_KEEPALIVE_TIMEOUT": {"test_value": 10},
    "PREFECT_SERVER_API_PORT": {"test_value": 4200},
    "PREFECT_SERVER_CONCURRENCY_LEASE_STORAGE": {
        "test_value": "prefect.server.concurrency.lease_storage.filesystem"
    },
    "PREFECT_SERVER_CORS_ALLOWED_HEADERS": {"test_value": "foo", "legacy": True},
    "PREFECT_SERVER_CORS_ALLOWED_METHODS": {"test_value": "foo", "legacy": True},
    "PREFECT_SERVER_CORS_ALLOWED_ORIGINS": {"test_value": "foo", "legacy": True},
    "PREFECT_SERVER_CSRF_PROTECTION_ENABLED": {"test_value": True, "legacy": True},
    "PREFECT_SERVER_CSRF_TOKEN_EXPIRATION": {
        "test_value": timedelta(seconds=10),
        "legacy": True,
    },
    "PREFECT_SERVER_DATABASE_CONNECTION_TIMEOUT": {"test_value": 10.0},
    "PREFECT_SERVER_DATABASE_CONNECTION_URL": {"test_value": "sqlite:///"},
    "PREFECT_SERVER_DATABASE_DRIVER": {"test_value": "sqlite+aiosqlite"},
    "PREFECT_SERVER_DATABASE_ECHO": {"test_value": True},
    "PREFECT_SERVER_DATABASE_HOST": {"test_value": "localhost"},
    "PREFECT_SERVER_DATABASE_MIGRATE_ON_START": {"test_value": True},
    "PREFECT_SERVER_DATABASE_NAME": {"test_value": "prefect"},
    "PREFECT_SERVER_DATABASE_PASSWORD": {"test_value": "password"},
    "PREFECT_SERVER_DATABASE_PORT": {"test_value": 5432},
    "PREFECT_SERVER_DATABASE_SQLALCHEMY_CONNECT_ARGS_APPLICATION_NAME": {
        "test_value": "prefect"
    },
    "PREFECT_SERVER_DATABASE_SQLALCHEMY_CONNECT_ARGS_PREPARED_STATEMENT_CACHE_SIZE": {
        "test_value": 1
    },
    "PREFECT_SERVER_DATABASE_SQLALCHEMY_CONNECT_ARGS_STATEMENT_CACHE_SIZE": {
        "test_value": 1
    },
    "PREFECT_SERVER_DATABASE_SQLALCHEMY_CONNECT_ARGS_TLS_CA_FILE": {"test_value": ""},
    "PREFECT_SERVER_DATABASE_SQLALCHEMY_CONNECT_ARGS_TLS_KEY_FILE": {"test_value": ""},
    "PREFECT_SERVER_DATABASE_SQLALCHEMY_CONNECT_ARGS_TLS_CERT_FILE": {"test_value": ""},
    "PREFECT_SERVER_DATABASE_SQLALCHEMY_CONNECT_ARGS_TLS_ENABLED": {
        "test_value": False
    },
    "PREFECT_SERVER_DATABASE_SQLALCHEMY_CONNECT_ARGS_TLS_CHECK_HOSTNAME": {
        "test_value": True
    },
    "PREFECT_SERVER_DATABASE_SQLALCHEMY_MAX_OVERFLOW": {"test_value": 10},
    "PREFECT_SERVER_DATABASE_SQLALCHEMY_POOL_RECYCLE": {"test_value": 10},
    "PREFECT_SERVER_DATABASE_SQLALCHEMY_POOL_SIZE": {"test_value": 10},
    "PREFECT_SERVER_DATABASE_SQLALCHEMY_POOL_TIMEOUT": {"test_value": 10.0},
    "PREFECT_SERVER_DATABASE_TIMEOUT": {"test_value": 10.0},
    "PREFECT_SERVER_DATABASE_USER": {"test_value": "user"},
    "PREFECT_SERVER_DEPLOYMENTS_CONCURRENCY_SLOT_WAIT_SECONDS": {"test_value": 10.0},
    "PREFECT_SERVER_DEPLOYMENT_SCHEDULE_MAX_SCHEDULED_RUNS": {"test_value": 10},
    "PREFECT_SERVER_EPHEMERAL_ENABLED": {"test_value": True},
    "PREFECT_SERVER_EPHEMERAL_STARTUP_TIMEOUT_SECONDS": {"test_value": 10},
    "PREFECT_SERVER_EVENTS_EXPIRED_BUCKET_BUFFER": {
        "test_value": timedelta(seconds=60)
    },
    "PREFECT_SERVER_EVENTS_MAXIMUM_EVENT_NAME_LENGTH": {"test_value": 1024},
    "PREFECT_SERVER_EVENTS_MAXIMUM_LABELS_PER_RESOURCE": {"test_value": 10},
    "PREFECT_SERVER_EVENTS_MAXIMUM_RELATED_RESOURCES": {"test_value": 10},
    "PREFECT_SERVER_EVENTS_MAXIMUM_SIZE_BYTES": {"test_value": 10},
    "PREFECT_SERVER_EVENTS_MAXIMUM_WEBSOCKET_BACKFILL": {
        "test_value": timedelta(minutes=15)
    },
    "PREFECT_SERVER_EVENTS_MESSAGING_BROKER": {"test_value": "broker"},
    "PREFECT_SERVER_EVENTS_MESSAGING_CACHE": {"test_value": "cache"},
    "PREFECT_SERVER_EVENTS_PROACTIVE_GRANULARITY": {"test_value": timedelta(seconds=5)},
    "PREFECT_SERVER_EVENTS_RELATED_RESOURCE_CACHE_TTL": {
        "test_value": timedelta(seconds=10)
    },
    "PREFECT_SERVER_EVENTS_RETENTION_PERIOD": {"test_value": timedelta(hours=7)},
    "PREFECT_SERVER_EVENTS_STREAM_OUT_ENABLED": {"test_value": True},
    "PREFECT_SERVER_EVENTS_WEBSOCKET_BACKFILL_PAGE_SIZE": {"test_value": 250},
    "PREFECT_SERVER_FLOW_RUN_GRAPH_MAX_ARTIFACTS": {"test_value": 10},
    "PREFECT_SERVER_FLOW_RUN_GRAPH_MAX_NODES": {"test_value": 100},
    "PREFECT_SERVER_LOGGING_LEVEL": {"test_value": "INFO"},
    "PREFECT_SERVER_LOG_RETRYABLE_ERRORS": {"test_value": True},
    "PREFECT_SERVER_LOGS_STREAM_OUT_ENABLED": {"test_value": True},
    "PREFECT_SERVER_LOGS_STREAM_PUBLISHING_ENABLED": {"test_value": True},
    "PREFECT_SERVER_MEMO_STORE_PATH": {"test_value": Path("/path/to/memo")},
    "PREFECT_SERVER_MEMOIZE_BLOCK_AUTO_REGISTRATION": {"test_value": True},
    "PREFECT_SERVER_METRICS_ENABLED": {"test_value": True},
    "PREFECT_SERVER_REGISTER_BLOCKS_ON_START": {"test_value": True},
    "PREFECT_SERVER_SERVICES_CANCELLATION_CLEANUP_ENABLED": {"test_value": True},
    "PREFECT_SERVER_SERVICES_CANCELLATION_CLEANUP_LOOP_SECONDS": {"test_value": 10.0},
    "PREFECT_SERVER_SERVICES_EVENT_LOGGER_ENABLED": {"test_value": True},
    "PREFECT_SERVER_SERVICES_EVENT_PERSISTER_BATCH_SIZE": {"test_value": 10},
    "PREFECT_SERVER_SERVICES_EVENT_PERSISTER_BATCH_SIZE_DELETE": {"test_value": 20},
    "PREFECT_SERVER_SERVICES_EVENT_PERSISTER_ENABLED": {"test_value": True},
    "PREFECT_SERVER_SERVICES_EVENT_PERSISTER_FLUSH_INTERVAL": {"test_value": 10.0},
    "PREFECT_SERVER_SERVICES_FOREMAN_DEPLOYMENT_LAST_POLLED_TIMEOUT_SECONDS": {
        "test_value": 10
    },
    "PREFECT_SERVER_SERVICES_FOREMAN_ENABLED": {"test_value": True},
    "PREFECT_SERVER_SERVICES_FOREMAN_FALLBACK_HEARTBEAT_INTERVAL_SECONDS": {
        "test_value": 10
    },
    "PREFECT_SERVER_SERVICES_FOREMAN_INACTIVITY_HEARTBEAT_MULTIPLE": {"test_value": 10},
    "PREFECT_SERVER_SERVICES_FOREMAN_LOOP_SECONDS": {"test_value": 10.0},
    "PREFECT_SERVER_SERVICES_FOREMAN_WORK_QUEUE_LAST_POLLED_TIMEOUT_SECONDS": {
        "test_value": 10
    },
    "PREFECT_SERVER_SERVICES_LATE_RUNS_AFTER_SECONDS": {
        "test_value": timedelta(seconds=15)
    },
    "PREFECT_SERVER_SERVICES_LATE_RUNS_ENABLED": {"test_value": True},
    "PREFECT_SERVER_SERVICES_LATE_RUNS_LOOP_SECONDS": {"test_value": 10.0},
    "PREFECT_SERVER_SERVICES_PAUSE_EXPIRATIONS_ENABLED": {"test_value": True},
    "PREFECT_SERVER_SERVICES_PAUSE_EXPIRATIONS_LOOP_SECONDS": {"test_value": 10.0},
    "PREFECT_SERVER_SERVICES_REPOSSESSOR_ENABLED": {"test_value": True},
    "PREFECT_SERVER_SERVICES_REPOSSESSOR_LOOP_SECONDS": {"test_value": 10.0},
    "PREFECT_SERVER_SERVICES_SCHEDULER_DEPLOYMENT_BATCH_SIZE": {"test_value": 10},
    "PREFECT_SERVER_SERVICES_SCHEDULER_ENABLED": {"test_value": True},
    "PREFECT_SERVER_SERVICES_SCHEDULER_INSERT_BATCH_SIZE": {"test_value": 10},
    "PREFECT_SERVER_SERVICES_SCHEDULER_LOOP_SECONDS": {"test_value": 10.0},
    "PREFECT_SERVER_SERVICES_SCHEDULER_MAX_RUNS": {"test_value": 10},
    "PREFECT_SERVER_SERVICES_SCHEDULER_MAX_SCHEDULED_TIME": {
        "test_value": timedelta(hours=10)
    },
    "PREFECT_SERVER_SERVICES_SCHEDULER_RECENT_DEPLOYMENTS_LOOP_SECONDS": {
        "test_value": 5.0
    },
    "PREFECT_SERVER_SERVICES_SCHEDULER_MIN_RUNS": {"test_value": 10},
    "PREFECT_SERVER_SERVICES_SCHEDULER_MIN_SCHEDULED_TIME": {
        "test_value": timedelta(minutes=10)
    },
    "PREFECT_SERVER_SERVICES_TASK_RUN_RECORDER_ENABLED": {"test_value": True},
    "PREFECT_SERVER_SERVICES_TRIGGERS_ENABLED": {"test_value": True},
    "PREFECT_SERVER_SERVICES_TRIGGERS_PG_NOTIFY_HEARTBEAT_INTERVAL_SECONDS": {
        "test_value": 5
    },
    "PREFECT_SERVER_SERVICES_TRIGGERS_PG_NOTIFY_RECONNECT_INTERVAL_SECONDS": {
        "test_value": 10
    },
    "PREFECT_SERVER_TASKS_MAX_CACHE_KEY_LENGTH": {"test_value": 10},
    "PREFECT_SERVER_TASKS_SCHEDULING_MAX_RETRY_QUEUE_SIZE": {"test_value": 10},
    "PREFECT_SERVER_TASKS_SCHEDULING_MAX_SCHEDULED_QUEUE_SIZE": {"test_value": 10},
    "PREFECT_SERVER_TASKS_SCHEDULING_PENDING_TASK_TIMEOUT": {
        "test_value": timedelta(seconds=10),
    },
    "PREFECT_SERVER_TASKS_TAG_CONCURRENCY_SLOT_WAIT_SECONDS": {
        "test_value": 10.0,
    },
    "PREFECT_SERVER_UI_API_URL": {"test_value": "https://api.prefect.io"},
    "PREFECT_SERVER_UI_ENABLED": {"test_value": True},
    "PREFECT_SERVER_UI_SERVE_BASE": {"test_value": "/base"},
    "PREFECT_SERVER_UI_STATIC_DIRECTORY": {"test_value": "/path/to/static"},
    "PREFECT_SILENCE_API_URL_MISCONFIGURATION": {"test_value": True},
    "PREFECT_SQLALCHEMY_MAX_OVERFLOW": {"test_value": 10, "legacy": True},
    "PREFECT_SQLALCHEMY_POOL_SIZE": {"test_value": 10, "legacy": True},
    "PREFECT_TASKS_DEFAULT_NO_CACHE": {"test_value": True},
    "PREFECT_TASKS_DEFAULT_PERSIST_RESULT": {"test_value": True},
    "PREFECT_TASKS_DEFAULT_RETRIES": {"test_value": 10},
    "PREFECT_TASKS_DEFAULT_RETRY_DELAY_SECONDS": {"test_value": 10},
    "PREFECT_TASKS_DISABLE_CACHING": {"test_value": False},
    "PREFECT_TASKS_REFRESH_CACHE": {"test_value": True},
    "PREFECT_TASKS_RUNNER_THREAD_POOL_MAX_WORKERS": {"test_value": 5},
    "PREFECT_TASKS_SCHEDULING_DEFAULT_STORAGE_BLOCK": {"test_value": "block"},
    "PREFECT_TASKS_SCHEDULING_DELETE_FAILED_SUBMISSIONS": {"test_value": True},
    "PREFECT_TASK_DEFAULT_RETRIES": {"test_value": 10, "legacy": True},
    "PREFECT_TASK_DEFAULT_RETRY_DELAY_SECONDS": {"test_value": 10, "legacy": True},
    "PREFECT_TASK_RUN_TAG_CONCURRENCY_SLOT_WAIT_SECONDS": {
        "test_value": 10,
        "legacy": True,
    },
    "PREFECT_TASK_SCHEDULING_DEFAULT_STORAGE_BLOCK": {
        "test_value": "block",
        "legacy": True,
    },
    "PREFECT_TASK_SCHEDULING_DELETE_FAILED_SUBMISSIONS": {
        "test_value": True,
        "legacy": True,
    },
    "PREFECT_TASK_SCHEDULING_MAX_RETRY_QUEUE_SIZE": {"test_value": 10, "legacy": True},
    "PREFECT_TASK_SCHEDULING_MAX_SCHEDULED_QUEUE_SIZE": {
        "test_value": 10,
        "legacy": True,
    },
    "PREFECT_TASK_SCHEDULING_PENDING_TASK_TIMEOUT": {
        "test_value": timedelta(seconds=10),
        "legacy": True,
    },
    "PREFECT_TESTING_TEST_MODE": {"test_value": True},
    "PREFECT_TESTING_TEST_SETTING": {"test_value": "bar"},
    "PREFECT_TESTING_UNIT_TEST_LOOP_DEBUG": {"test_value": True},
    "PREFECT_TESTING_UNIT_TEST_MODE": {"test_value": True},
    "PREFECT_TEST_MODE": {"test_value": True, "legacy": True},
    "PREFECT_TEST_SETTING": {"test_value": "bar", "legacy": True},
    "PREFECT_UI_API_URL": {"test_value": "https://api.prefect.io", "legacy": True},
    "PREFECT_UI_ENABLED": {"test_value": True, "legacy": True},
    "PREFECT_UI_SERVE_BASE": {"test_value": "/base", "legacy": True},
    "PREFECT_UI_STATIC_DIRECTORY": {"test_value": "/path/to/static", "legacy": True},
    "PREFECT_UI_URL": {"test_value": "https://ui.prefect.io"},
    "PREFECT_UNIT_TEST_LOOP_DEBUG": {"test_value": True, "legacy": True},
    "PREFECT_UNIT_TEST_MODE": {"test_value": True, "legacy": True},
    "PREFECT_WORKER_HEARTBEAT_SECONDS": {"test_value": 10.0},
    "PREFECT_WORKER_PREFETCH_SECONDS": {"test_value": 10.0},
    "PREFECT_WORKER_QUERY_SECONDS": {"test_value": 10.0},
    "PREFECT_WORKER_WEBSERVER_HOST": {"test_value": "host"},
    "PREFECT_WORKER_WEBSERVER_PORT": {"test_value": 8080},
    "PREFECT_TASK_RUNNER_THREAD_POOL_MAX_WORKERS": {"test_value": 5, "legacy": True},
}


@pytest.fixture
def temporary_env_file(tmp_path: Path) -> Generator[Callable[[str], None], None, None]:
    with tmpchdir(str(tmp_path)):
        env_file = Path(".env")

        def _create_temp_env(content: str) -> None:
            env_file.write_text(content)

        yield _create_temp_env

        if env_file.exists():
            env_file.unlink()


@pytest.fixture
def temporary_toml_file(tmp_path: Path) -> Generator[Callable[[str], None], None, None]:
    with tmpchdir(str(tmp_path)):
        toml_file = Path("prefect.toml")

        def _create_temp_toml(content: str, path: Path = toml_file) -> None:
            nonlocal toml_file
            with path.open("w") as f:
                toml.dump(content, f)  # type: ignore
            toml_file = path  # update toml_file in case path was changed

        yield _create_temp_toml

        if toml_file.exists():
            toml_file.unlink()


class TestSettingClass:
    def test_setting_equality_with_value(self):
        with temporary_settings({PREFECT_TEST_SETTING: "foo"}):
            assert PREFECT_TEST_SETTING == "foo"
            assert PREFECT_TEST_SETTING != "bar"

    def test_setting_equality_with_self(self):
        assert PREFECT_TEST_SETTING == PREFECT_TEST_SETTING

    def test_setting_equality_with_other_setting(self):
        assert PREFECT_TEST_SETTING != PREFECT_TEST_MODE

    def test_setting_hash_is_consistent(self):
        assert hash(PREFECT_TEST_SETTING) == hash(PREFECT_TEST_SETTING)

    def test_setting_hash_is_unique(self):
        assert hash(PREFECT_TEST_SETTING) != hash(PREFECT_LOGGING_LEVEL)

    def test_setting_hash_consistent_on_value_change(self):
        original = hash(PREFECT_TEST_SETTING)
        with temporary_settings({PREFECT_TEST_SETTING: "foo"}):
            assert hash(PREFECT_TEST_SETTING) == original

    def test_setting_hash_is_consistent_after_deepcopy(self):
        assert hash(PREFECT_TEST_SETTING) == hash(copy.deepcopy(PREFECT_TEST_SETTING))


class TestSettingsClass:
    def test_settings_copy_with_update_does_not_mark_unset_as_set(self):
        settings = get_current_settings()
        set_keys = set(settings.model_dump(exclude_unset=True).keys())
        new_settings = settings.copy_with_update()
        new_set_keys = set(new_settings.model_dump(exclude_unset=True).keys())
        assert new_set_keys == set_keys

        new_settings = settings.copy_with_update(updates={PREFECT_TEST_SETTING: "TEST"})
        new_set_keys = set(new_settings.model_dump(exclude_unset=True).keys())
        assert new_set_keys == set_keys

        set_testing_keys = set(settings.testing.model_dump(exclude_unset=True).keys())
        new_set_testing_keys = set(
            new_settings.testing.model_dump(exclude_unset=True).keys()
        )
        assert new_set_testing_keys - set_testing_keys == {"test_setting"}

    def test_settings_copy_with_update(self):
        settings = get_current_settings()
        assert settings.testing.unit_test_mode is True

        with temporary_settings(restore_defaults={PREFECT_API_KEY}):
            new_settings = settings.copy_with_update(
                updates={PREFECT_CLIENT_RETRY_EXTRA_CODES: "400,500"},
                set_defaults={PREFECT_UNIT_TEST_MODE: False, PREFECT_API_KEY: "TEST"},
            )
            assert new_settings.testing.unit_test_mode is True, (
                "Not changed, existing value was not default"
            )
            assert (
                new_settings.api.key is not None
                and new_settings.api.key.get_secret_value() == "TEST"
            ), "Changed, existing value was default"
            assert new_settings.client.retry_extra_codes == {400, 500}

    def test_settings_copy_with_update_restore_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("PREFECT_TESTING_TEST_SETTING", "Not the default")
        settings = Settings()
        assert settings.testing.test_setting == "Not the default"
        new_settings = settings.copy_with_update(
            restore_defaults={PREFECT_TEST_SETTING},
        )
        assert new_settings.testing.test_setting == "FOO"

    def test_settings_loads_environment_variables_at_instantiation(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        assert PREFECT_TEST_MODE.value() is True

        monkeypatch.setenv("PREFECT_TESTING_TEST_MODE", "0")
        new_settings = Settings()
        assert PREFECT_TEST_MODE.value_from(new_settings) is False

    @pytest.mark.usefixtures("disable_hosted_api_server")
    def test_settings_to_environment_includes_all_settings_with_non_null_values(self):
        settings = Settings()
        expected_names = {
            s.name
            for s in _get_settings_fields(Settings).values()
            if s.value() is not None
        }
        for name, metadata in SUPPORTED_SETTINGS.items():
            if metadata.get("legacy") and name in expected_names:
                expected_names.remove(name)
        assert set(settings.to_environment_variables().keys()) == expected_names

    def test_settings_to_environment_works_with_exclude_unset(self):
        assert Settings(
            server=ServerSettings(api=ServerAPISettings(port=3000))
        ).to_environment_variables(exclude_unset=True) == {
            # From env
            **{
                var: os.environ[var] for var in os.environ if var.startswith("PREFECT_")
            },
            # From test settings
            "PREFECT_SERVER_LOGGING_LEVEL": "DEBUG",
            "PREFECT_TESTING_TEST_MODE": "True",
            "PREFECT_TESTING_UNIT_TEST_MODE": "True",
            # From init
            "PREFECT_SERVER_API_PORT": "3000",
        }

    def test_settings_to_environment_casts_to_strings(self):
        assert (
            Settings(
                server=ServerSettings(api=ServerAPISettings(port=3000))
            ).to_environment_variables()["PREFECT_SERVER_API_PORT"]
            == "3000"
        )
        assert (
            Settings(
                logging=LoggingSettings(extra_loggers="foo")
            ).to_environment_variables()["PREFECT_LOGGING_EXTRA_LOGGERS"]
            == "foo"
        )
        assert Settings(
            logging=LoggingSettings(extra_loggers=["foo", "bar"])
        ).to_environment_variables()["PREFECT_LOGGING_EXTRA_LOGGERS"] in (
            "foo,bar",
            "bar,foo",
        )
        assert (
            Settings(
                client=ClientSettings(retry_extra_codes=300)
            ).to_environment_variables()["PREFECT_CLIENT_RETRY_EXTRA_CODES"]
            == "300"
        )
        assert Settings(
            client=ClientSettings(retry_extra_codes={300, 400})
        ).to_environment_variables()["PREFECT_CLIENT_RETRY_EXTRA_CODES"] in (
            "300,400",
            "400,300",
        )

    @pytest.mark.parametrize("exclude_unset", [True, False])
    def test_settings_to_environment_roundtrip(
        self,
        exclude_unset: bool,
        monkeypatch: pytest.MonkeyPatch,
    ):
        settings = Settings()
        variables = settings.to_environment_variables(exclude_unset=exclude_unset)
        for key, value in variables.items():
            monkeypatch.setenv(key, value)
        new_settings = Settings()
        assert settings.model_dump() == new_settings.model_dump()

    @pytest.mark.parametrize(
        "settings,alias,expected",
        [
            (
                Settings(server=ServerSettings(logging_level="DEBUG")),
                "PREFECT_LOGGING_SERVER_LEVEL",
                "DEBUG",
            ),
            (
                Settings(results=ResultsSettings(default_storage_block="foo/bar")),
                "PREFECT_DEFAULT_RESULT_STORAGE_BLOCK",
                "foo/bar",
            ),
        ],
    )
    def test_settings_to_environment_includes_aliases(
        self, settings: Settings, alias: str, expected: str
    ):
        assert (
            settings.to_environment_variables(include_aliases=True).get(alias)
            == expected
        )

    @pytest.mark.parametrize(
        "alias",
        ["PREFECT_LOGGING_SERVER_LEVEL", "PREFECT_DEFAULT_RESULT_STORAGE_BLOCK"],
    )
    def test_settings_to_environment_doesnt_include_aliases_by_default(
        self, alias: str
    ):
        assert (
            Settings().to_environment_variables(include_aliases=False).get(alias)
            is None
        )

    def test_settings_hash_key(self):
        settings = Settings(testing=dict(test_mode=True))  # type: ignore
        diff_settings = Settings(testing=dict(test_mode=False))  # type: ignore

        assert settings.hash_key() == settings.hash_key()

        assert settings.hash_key() != diff_settings.hash_key()

    @pytest.mark.parametrize(
        "log_level_setting",
        [
            PREFECT_LOGGING_LEVEL,
            PREFECT_SERVER_LOGGING_LEVEL,
            PREFECT_LOGGING_SERVER_LEVEL,
        ],
    )
    def test_settings_validates_log_levels(
        self,
        log_level_setting: Setting,
        monkeypatch: pytest.MonkeyPatch,
    ):
        with pytest.raises(
            pydantic.ValidationError,
            match="should be 'DEBUG', 'INFO', 'WARNING', 'ERROR' or 'CRITICAL'",
        ):
            kwargs: dict[str, Any] = {}
            set_in_dict(kwargs, log_level_setting.accessor, "FOOBAR")
            Settings(**kwargs)

    @pytest.mark.parametrize(
        "log_level_setting",
        [
            PREFECT_LOGGING_LEVEL,
            PREFECT_SERVER_LOGGING_LEVEL,
        ],
    )
    def test_settings_uppercases_log_levels(
        self,
        log_level_setting: Setting,
    ):
        with temporary_settings({log_level_setting: "debug"}):
            assert log_level_setting.value() == "DEBUG"

    def test_equality_of_new_instances(self):
        assert Settings() == Settings()

    def test_equality_after_deep_copy(self):
        settings = Settings()
        assert copy.deepcopy(settings) == settings

    def test_equality_with_different_values(self):
        settings = Settings()
        assert (
            settings.copy_with_update(updates={PREFECT_TEST_SETTING: "foo"}) != settings
        )

    def test_include_secrets(self):
        settings = Settings(api=APISettings(key=pydantic.SecretStr("test")))

        assert get_from_dict(settings.model_dump(), "api.key") == pydantic.SecretStr(
            "test"
        )
        assert (
            get_from_dict(settings.model_dump(mode="json"), "api.key") == "**********"
        )
        assert (
            get_from_dict(
                settings.model_dump(context={"include_secrets": True}), "api.key"
            )
            == "test"
        )

    def test_loads_when_profile_path_does_not_exist(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("PREFECT_PROFILES_PATH", str(Path.home() / "nonexistent"))
        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)
        assert Settings().testing.test_setting == "FOO"
        # Should default to ephemeral profile
        assert Settings().server.ephemeral.enabled

    def test_loads_when_profile_path_is_not_a_toml_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setenv("PREFECT_PROFILES_PATH", str(tmp_path / "profiles.toml"))
        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)

        with open(tmp_path / "profiles.toml", "w") as f:
            f.write("Ceci n'est pas un fichier toml")

        with pytest.warns(UserWarning, match="Failed to load profiles from"):
            assert Settings().testing.test_setting == "FOO"

    def test_valid_setting_names_matches_supported_settings(self):
        assert set(_get_valid_setting_names(Settings)) == set(
            SUPPORTED_SETTINGS.keys()
        ), (
            "valid_setting_names output did not match supported settings. Please update SUPPORTED_SETTINGS if you are adding or removing a setting."
        )


class TestSettingAccess:
    def test_get_value_root_setting(self):
        with temporary_settings(
            updates={PREFECT_API_URL: "test"}
        ):  # Set a value so its not null
            assert PREFECT_API_URL.value() == "test"
            assert get_current_settings().api.url == "test"

    def test_get_value_nested_setting(self):
        value = prefect.settings.PREFECT_LOGGING_LEVEL.value()
        value_of = get_current_settings().logging.level
        value_from = PREFECT_LOGGING_LEVEL.value_from(get_current_settings())
        assert value == value_of == value_from

    def test_test_mode_access(self):
        assert PREFECT_TEST_MODE.value() is True

    def test_settings_in_truthy_statements_use_value(self):
        if PREFECT_TEST_MODE:
            assert True, "Treated as truth"
        else:
            assert False, "Not treated as truth"

        with temporary_settings(updates={PREFECT_TEST_MODE: False}):
            if not PREFECT_TEST_MODE:
                assert True, "Treated as truth"
            else:
                assert False, "Not treated as truth"

        # Test with a non-boolean setting

        if PREFECT_SERVER_API_HOST:
            assert True, "Treated as truth"
        else:
            assert False, "Not treated as truth"

        with temporary_settings(updates={PREFECT_SERVER_API_HOST: ""}):
            if not PREFECT_SERVER_API_HOST:
                assert True, "Treated as truth"
            else:
                assert False, "Not treated as truth"

    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, []),
            ("foo", ["foo"]),
            ("foo,bar", ["foo", "bar"]),
            ("foo, bar, foobar ", ["foo", "bar", "foobar"]),
            (["foo", "bar"], ["foo", "bar"]),
        ],
        ids=[
            "none",
            "string",
            "comma_separated",
            "comma_separated_with_spaces",
            "python_list",
        ],
    )
    def test_extra_loggers(self, value: str | list[str], expected: list[str]):
        settings = Settings(logging=LoggingSettings(extra_loggers=value))
        assert set(PREFECT_LOGGING_EXTRA_LOGGERS.value_from(settings)) == set(expected)

    def test_prefect_home_expands_tilde_in_path(self):
        settings = Settings(home="~/test")  # type: ignore
        assert PREFECT_HOME.value_from(settings) == Path("~/test").expanduser()

    @pytest.mark.parametrize(
        "api_url,ui_url",
        [
            (None, None),
            (
                "https://api.prefect.cloud/api/accounts/ACCOUNT/workspaces/WORKSPACE",
                "https://app.prefect.cloud/account/ACCOUNT/workspace/WORKSPACE",
            ),
            ("http://my-orion/api", "http://my-orion"),
            ("https://api.foo.bar", "https://api.foo.bar"),
        ],
    )
    def test_ui_url_inferred_from_api_url(self, api_url: str, ui_url: str):
        with temporary_settings({PREFECT_API_URL: api_url}):
            assert PREFECT_UI_URL.value() == ui_url

    def test_ui_url_set_directly(self):
        with temporary_settings({PREFECT_UI_URL: "test"}):
            assert PREFECT_UI_URL.value() == "test"

    @pytest.mark.parametrize(
        "api_url,ui_url",
        [
            # We'll infer that app. and api. subdomains go together for prefect domains
            (
                "https://api.prefect.cloud/api",
                "https://app.prefect.cloud",
            ),
            (
                "https://api.theoretical.prefect.bonkers/api",
                "https://app.theoretical.prefect.bonkers",
            ),
            (
                "https://api.prefect.banooners/api",
                "https://app.prefect.banooners",
            ),
            # We'll leave URLs with non-prefect TLDs alone
            (
                "https://api.theoretical.prefect.customer.com/api",
                "https://api.theoretical.prefect.customer.com",
            ),
            # Some day, some day...
            (
                "https://api.prefect/api",
                "https://api.prefect",
            ),
            # We'll leave all other URLs alone
            ("http://prefect/api", "http://prefect"),
            ("http://my-cloud/api", "http://my-cloud"),
            ("https://api.foo.bar", "https://api.foo.bar"),
        ],
    )
    def test_cloud_ui_url_inferred_from_cloud_api_url(self, api_url: str, ui_url: str):
        with temporary_settings({PREFECT_CLOUD_API_URL: api_url}):
            assert PREFECT_CLOUD_UI_URL.value() == ui_url

    def test_cloud_ui_url_set_directly(self):
        with temporary_settings({PREFECT_CLOUD_UI_URL: "test"}):
            assert PREFECT_CLOUD_UI_URL.value() == "test"

    def test_ui_api_url_inferred_from_api_url(self):
        with temporary_settings({PREFECT_API_URL: "http://my-domain/api"}):
            assert PREFECT_UI_API_URL.value() == "http://my-domain/api"

    def test_ui_api_url_set_directly(self):
        with temporary_settings({PREFECT_UI_API_URL: "http://my-foo-domain/api"}):
            assert PREFECT_UI_API_URL.value() == "http://my-foo-domain/api"

    def test_ui_api_url_default(self):
        default_api_url = PREFECT_API_URL.value()
        assert PREFECT_UI_API_URL.value() == default_api_url

        assert default_api_url.startswith("http://localhost")
        assert default_api_url.endswith("/api")

    @pytest.mark.parametrize(
        "extra_codes,expected",
        [
            ("", set()),
            ("400", {400}),
            ("400,400,400", {400}),
            ("400,500", {400, 500}),
            ("400, 401, 402", {400, 401, 402}),
        ],
    )
    def test_client_retry_extra_codes(self, extra_codes: str, expected: set[int]):
        with temporary_settings({PREFECT_CLIENT_RETRY_EXTRA_CODES: extra_codes}):
            assert PREFECT_CLIENT_RETRY_EXTRA_CODES.value() == expected

    @pytest.mark.parametrize(
        "extra_codes",
        [
            "foo",
            "-1",
            "0",
            "10",
            "400,foo",
            "400,500,foo",
        ],
    )
    def test_client_retry_extra_codes_invalid(self, extra_codes: str):
        with pytest.raises(ValueError):
            with temporary_settings({PREFECT_CLIENT_RETRY_EXTRA_CODES: extra_codes}):
                PREFECT_CLIENT_RETRY_EXTRA_CODES.value()

    def test_default_task_retry_delay_seconds(self):
        sample_values_and_expected = (
            (None, None),
            ("", None),
            ("10", 10.0),
            ("10,20,30", [10.0, 20.0, 30.0]),
            ("10.0", 10.0),
            (10, 10.0),
            ([10, 20, 30], [10.0, 20.0, 30.0]),
        )
        for retry_delay_plaintext_value, expected in sample_values_and_expected:
            with temporary_settings(
                {PREFECT_TASK_DEFAULT_RETRY_DELAY_SECONDS: retry_delay_plaintext_value}
            ):
                assert PREFECT_TASK_DEFAULT_RETRY_DELAY_SECONDS.value() == expected

    def test_deprecated_ENV_VAR_attribute_access(self):
        settings = Settings()
        value = None
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            value = settings.PREFECT_TEST_MODE

            assert len(w) == 1
            assert issubclass(w[-1].category, DeprecationWarning)
            assert (
                "Accessing `Settings().PREFECT_TEST_MODE` is deprecated. Use `Settings().testing.test_mode` instead."
                in str(w[-1].message)
            )

        assert value == settings.testing.test_mode

    def test_settings_with_serialization_alias(self, monkeypatch: pytest.MonkeyPatch):
        assert not Settings().client.metrics.enabled
        # Use old value
        monkeypatch.setenv("PREFECT_CLIENT_ENABLE_METRICS", "True")
        assert Settings().client.metrics.enabled

        monkeypatch.delenv("PREFECT_CLIENT_ENABLE_METRICS", raising=False)
        assert not Settings().client.metrics.enabled

        # Use new value
        monkeypatch.setenv("PREFECT_CLIENT_METRICS_ENABLED", "True")
        assert Settings().client.metrics.enabled

        # Check both can be imported
        from prefect.settings import (
            PREFECT_CLIENT_ENABLE_METRICS,
            PREFECT_CLIENT_METRICS_ENABLED,
        )

        assert isinstance(PREFECT_CLIENT_ENABLE_METRICS, Setting)
        assert isinstance(PREFECT_CLIENT_METRICS_ENABLED, Setting)


class TestDatabaseSettings:
    def test_database_connection_url_templates_password(self):
        with temporary_settings(
            {
                PREFECT_SERVER_DATABASE_CONNECTION_URL: (
                    "${PREFECT_API_DATABASE_PASSWORD}/test"
                ),
                PREFECT_API_DATABASE_PASSWORD: "password",
            }
        ):
            assert PREFECT_SERVER_DATABASE_CONNECTION_URL.value() == "password/test"

    def test_database_connection_url_raises_on_null_password(self):
        # Not exactly beautiful behavior here, but I think it's clear.
        # In the future, we may want to consider raising if attempting to template
        # a null value.
        with pytest.raises(ValueError, match="database password is None"):
            with temporary_settings(
                {
                    PREFECT_SERVER_DATABASE_CONNECTION_URL: (
                        "${PREFECT_API_DATABASE_PASSWORD}/test"
                    )
                }
            ):
                pass

    def test_warning_if_database_password_set_without_template_string(self):
        with pytest.warns(
            UserWarning,
            match=(
                "PREFECT_SERVER_DATABASE_PASSWORD is set but not included in the "
                "PREFECT_SERVER_DATABASE_CONNECTION_URL. "
                "The provided password will be ignored."
            ),
        ):
            with temporary_settings(
                {
                    PREFECT_SERVER_DATABASE_CONNECTION_URL: "test",
                    PREFECT_API_DATABASE_PASSWORD: "password",
                }
            ):
                pass

    def test_postgres_database_settings_may_be_set_individually(self):
        with temporary_settings(
            {
                PREFECT_SERVER_DATABASE_CONNECTION_URL: None,
                PREFECT_API_DATABASE_DRIVER: "postgresql+asyncpg",
                PREFECT_API_DATABASE_HOST: "the-database-server.example.com",
                PREFECT_API_DATABASE_PORT: 15432,
                PREFECT_API_DATABASE_USER: "the-user",
                PREFECT_API_DATABASE_NAME: "the-database",
                PREFECT_API_DATABASE_PASSWORD: "the-password",
            }
        ):
            url = make_url(PREFECT_SERVER_DATABASE_CONNECTION_URL.value())
            assert url.drivername == "postgresql+asyncpg"
            assert url.host == "the-database-server.example.com"
            assert url.port == 15432
            assert url.username == "the-user"
            assert url.database == "the-database"
            assert url.password == "the-password"

    def test_postgres_connection_url_is_secret_when_parts_are_individually_set(self):
        """
        Regression test for https://github.com/PrefectHQ/prefect/issues/16657
        """
        with temporary_settings(
            {
                PREFECT_SERVER_DATABASE_CONNECTION_URL: None,
                PREFECT_API_DATABASE_DRIVER: "postgresql+asyncpg",
                PREFECT_API_DATABASE_HOST: "the-database-server.example.com",
                PREFECT_API_DATABASE_PORT: 15432,
                PREFECT_API_DATABASE_USER: "the-user",
                PREFECT_API_DATABASE_NAME: "the-database",
                PREFECT_API_DATABASE_PASSWORD: "the-password",
            }
        ):
            assert isinstance(
                get_current_settings().server.database.connection_url,
                pydantic.SecretStr,
            )

    def test_postgres_password_is_quoted(self):
        with temporary_settings(
            {
                PREFECT_SERVER_DATABASE_CONNECTION_URL: None,
                PREFECT_API_DATABASE_DRIVER: "postgresql+asyncpg",
                PREFECT_API_DATABASE_HOST: "the-database-server.example.com",
                PREFECT_API_DATABASE_PORT: 15432,
                PREFECT_API_DATABASE_USER: "the-user",
                PREFECT_API_DATABASE_NAME: "the-database",
                PREFECT_API_DATABASE_PASSWORD: "the-password:has:funky!@stuff",
            }
        ):
            url = make_url(PREFECT_SERVER_DATABASE_CONNECTION_URL.value())
            assert url.drivername == "postgresql+asyncpg"
            assert url.host == "the-database-server.example.com"
            assert url.port == 15432
            assert url.username == "the-user"
            assert url.database == "the-database"
            assert url.password == "the-password:has:funky!@stuff"

    def test_postgres_database_settings_defaults_port(self):
        with temporary_settings(
            {
                PREFECT_SERVER_DATABASE_CONNECTION_URL: None,
                PREFECT_API_DATABASE_DRIVER: "postgresql+asyncpg",
                PREFECT_API_DATABASE_HOST: "the-database-server.example.com",
                PREFECT_API_DATABASE_USER: "the-user",
                PREFECT_API_DATABASE_NAME: "the-database",
                PREFECT_API_DATABASE_PASSWORD: "the-password",
            }
        ):
            url = make_url(PREFECT_SERVER_DATABASE_CONNECTION_URL.value())
            assert url.drivername == "postgresql+asyncpg"
            assert url.host == "the-database-server.example.com"
            assert url.port == 5432
            assert url.username == "the-user"
            assert url.database == "the-database"
            assert url.password == "the-password"

    def test_sqlite_database_settings_may_be_set_individually(self):
        with temporary_settings(
            {
                PREFECT_SERVER_DATABASE_CONNECTION_URL: None,
                PREFECT_API_DATABASE_DRIVER: "sqlite+aiosqlite",
                PREFECT_API_DATABASE_NAME: "/the/database/file/path.db",
            }
        ):
            url = make_url(PREFECT_SERVER_DATABASE_CONNECTION_URL.value())
            assert url.drivername == "sqlite+aiosqlite"
            assert url.database == "/the/database/file/path.db"

    def test_sqlite_database_driver_uses_default_path(self):
        with temporary_settings(
            {
                PREFECT_SERVER_DATABASE_CONNECTION_URL: None,
                PREFECT_API_DATABASE_DRIVER: "sqlite+aiosqlite",
            }
        ):
            url = make_url(PREFECT_SERVER_DATABASE_CONNECTION_URL.value())
            assert url.drivername == "sqlite+aiosqlite"
            assert url.database == f"{PREFECT_HOME.value()}/prefect.db"

    def test_unknown_driver_raises(self):
        with pytest.raises(pydantic.ValidationError, match="literal_error"):
            with temporary_settings(
                {
                    PREFECT_SERVER_DATABASE_CONNECTION_URL: None,
                    PREFECT_API_DATABASE_DRIVER: "wat",
                }
            ):
                pass

    def test_connection_string_with_dollar_sign(self):
        """
        Regression test for https://github.com/PrefectHQ/prefect/issues/11067.

        This test ensures that passwords with dollar signs do not cause issues when
        templating the connection string.
        """
        with temporary_settings(
            {
                PREFECT_SERVER_DATABASE_CONNECTION_URL: (
                    "postgresql+asyncpg://"
                    "the-user:the-$password@"
                    "the-database-server.example.com:5432"
                    "/the-database"
                ),
                PREFECT_API_DATABASE_USER: "the-user",
            }
        ):
            url = make_url(PREFECT_SERVER_DATABASE_CONNECTION_URL.value())
            assert url.drivername == "postgresql+asyncpg"
            assert url.host == "the-database-server.example.com"
            assert url.port == 5432
            assert url.username == "the-user"
            assert url.database == "the-database"
            assert url.password == "the-$password"

    def test_sqlalchemy_settings_migration(self):
        """Test that SQLAlchemy settings work with both old and new structures."""

        with pytest.warns(
            DeprecationWarning, match="moved to the `sqlalchemy` settings group."
        ):
            settings_with_old_keys = Settings(
                server=ServerSettings(
                    database=ServerDatabaseSettings(
                        sqlalchemy_pool_size=42,
                        sqlalchemy_max_overflow=37,
                    )
                )
            )
            assert settings_with_old_keys.server.database.sqlalchemy_pool_size == 42
            assert settings_with_old_keys.server.database.sqlalchemy_max_overflow == 37

        assert settings_with_old_keys.server.database.sqlalchemy.pool_size == 42
        assert settings_with_old_keys.server.database.sqlalchemy.max_overflow == 37

        settings_with_new_keys = Settings(
            server=ServerSettings(
                database=ServerDatabaseSettings(
                    sqlalchemy=SQLAlchemySettings(
                        pool_size=42,
                        max_overflow=37,
                    )
                )
            )
        )

        with pytest.warns(
            DeprecationWarning, match="moved to the `sqlalchemy` settings group."
        ):
            assert settings_with_new_keys.server.database.sqlalchemy_pool_size == 42
            assert settings_with_new_keys.server.database.sqlalchemy_max_overflow == 37

        # new keys are updated by setting new keys
        assert settings_with_new_keys.server.database.sqlalchemy.pool_size == 42
        assert settings_with_new_keys.server.database.sqlalchemy.max_overflow == 37

    def test_sqlalchemy_settings_migration_via_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("PREFECT_SERVER_DATABASE_SQLALCHEMY_POOL_SIZE", "128")
        monkeypatch.setenv("PREFECT_SERVER_DATABASE_SQLALCHEMY_MAX_OVERFLOW", "9001")
        assert Settings().server.database.sqlalchemy.pool_size == 128
        assert Settings().server.database.sqlalchemy.max_overflow == 9001

    def test_sqlalchemy_settings_migration_via_toml(
        self, temporary_toml_file: Callable[..., None]
    ):
        """Test that SQLAlchemy settings can be configured via TOML files."""
        toml_data: dict[str, Any] = {
            "server": {
                "database": {
                    "sqlalchemy": {
                        "pool_size": 42,
                        "max_overflow": 37,
                    }
                }
            }
        }
        temporary_toml_file(toml_data)

        settings = Settings()
        assert settings.server.database.sqlalchemy.pool_size == 42
        assert settings.server.database.sqlalchemy.max_overflow == 37

        with pytest.warns(
            DeprecationWarning, match="moved to the `sqlalchemy` settings group."
        ):
            assert settings.server.database.sqlalchemy_pool_size == 42
            assert settings.server.database.sqlalchemy_max_overflow == 37


class TestTemporarySettings:
    def test_temporary_settings(self):
        assert PREFECT_TEST_MODE.value() is True
        with temporary_settings(updates={PREFECT_TEST_MODE: False}) as new_settings:
            assert PREFECT_TEST_MODE.value_from(new_settings) is False, (
                "Yields the new settings"
            )
            assert PREFECT_TEST_MODE.value() is False

        assert PREFECT_TEST_MODE.value() is True

    def test_temporary_settings_does_not_mark_unset_as_set(self):
        settings = get_current_settings()
        set_keys = set(settings.model_dump(exclude_unset=True).keys())
        with temporary_settings() as new_settings:
            pass
        new_set_keys = set(new_settings.model_dump(exclude_unset=True).keys())
        assert new_set_keys == set_keys

    def test_temporary_settings_can_restore_to_defaults_values(self):
        with temporary_settings(updates={PREFECT_API_DATABASE_PORT: 9001}):
            assert PREFECT_API_DATABASE_PORT.value() == 9001
            with temporary_settings(restore_defaults={PREFECT_API_DATABASE_PORT}):
                assert (
                    PREFECT_API_DATABASE_PORT.value()
                    == PREFECT_API_DATABASE_PORT.default()
                )

    def test_temporary_settings_restores_on_error(self):
        assert PREFECT_TEST_MODE.value() is True

        with pytest.raises(ValueError):
            with temporary_settings(updates={PREFECT_TEST_MODE: False}):
                raise ValueError()

        assert os.environ["PREFECT_TESTING_TEST_MODE"] == "1", (
            "Does not alter os environ."
        )
        assert PREFECT_TEST_MODE.value() is True


class TestSettingsSources:
    def test_env_source(self, temporary_env_file: Callable[[str], None]):
        temporary_env_file("PREFECT_CLIENT_RETRY_EXTRA_CODES=420,500")

        assert Settings().client.retry_extra_codes == {420, 500}

        os.unlink(".env")

        assert Settings().client.retry_extra_codes == set()

    def test_resolution_order(
        self,
        temporary_env_file: Callable[[str], None],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        profiles_path = tmp_path / "profiles.toml"

        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)
        monkeypatch.setenv("PREFECT_PROFILES_PATH", str(profiles_path))

        profiles_path.write_text(
            textwrap.dedent(
                """
                active = "foo"

                [profiles.foo]
                PREFECT_CLIENT_RETRY_EXTRA_CODES = "420,500"
                """
            )
        )

        assert Settings().client.retry_extra_codes == {420, 500}

        pyproject_toml_data = {
            "tool": {"prefect": {"client": {"retry_extra_codes": "200"}}}
        }
        with open("pyproject.toml", "w") as f:
            toml.dump(pyproject_toml_data, f)

        assert Settings().client.retry_extra_codes == {200}

        prefect_toml_data = {"client": {"retry_extra_codes": "300"}}
        with open("prefect.toml", "w") as f:
            toml.dump(prefect_toml_data, f)

        assert Settings().client.retry_extra_codes == {300}

        temporary_env_file("PREFECT_CLIENT_RETRY_EXTRA_CODES=429,500")

        assert Settings().client.retry_extra_codes == {429, 500}

        os.unlink(".env")

        assert Settings().client.retry_extra_codes == {300}

        os.unlink("prefect.toml")

        assert Settings().client.retry_extra_codes == {200}

        os.unlink("pyproject.toml")

        assert Settings().client.retry_extra_codes == {420, 500}

        monkeypatch.setenv("PREFECT_TEST_MODE", "1")
        monkeypatch.setenv("PREFECT_TESTING_UNIT_TEST_MODE", "1")
        monkeypatch.delenv("PREFECT_PROFILES_PATH", raising=True)

        assert Settings().client.retry_extra_codes == set()

    def test_read_legacy_setting_from_profile(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        Settings().client.metrics.enabled = False
        profiles_path = tmp_path / "profiles.toml"

        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)
        monkeypatch.setenv("PREFECT_PROFILES_PATH", str(profiles_path))

        profiles_path.write_text(
            textwrap.dedent(
                """
                active = "foo"

                [profiles.foo]
                PREFECT_CLIENT_ENABLE_METRICS = "True"
                """
            )
        )

        assert Settings().client.metrics.enabled is True

    def test_resolution_order_with_nested_settings(
        self,
        temporary_env_file: Callable[[str], None],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        profiles_path = tmp_path / "profiles.toml"

        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)
        monkeypatch.setenv("PREFECT_PROFILES_PATH", str(profiles_path))

        profiles_path.write_text(
            textwrap.dedent(
                """
                active = "foo"

                [profiles.foo]
                PREFECT_API_URL = "http://example.com:4200"
                """
            )
        )

        assert Settings().api.url == "http://example.com:4200"

        temporary_env_file("PREFECT_API_URL=http://localhost:4200")

        assert Settings().api.url == "http://localhost:4200"

        os.unlink(".env")

        assert Settings().api.url == "http://example.com:4200"

    def test_profiles_path_from_env_source(
        self,
        temporary_env_file: Callable[[str], None],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        profiles_path = tmp_path / "custom_profiles.toml"

        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)

        profiles_path.write_text(
            textwrap.dedent(
                """
                active = "foo"

                [profiles.foo]
                PREFECT_CLIENT_RETRY_EXTRA_CODES = "420,500"
                """
            )
        )

        temporary_env_file(f"PREFECT_PROFILES_PATH={profiles_path}")

        assert Settings().profiles_path == profiles_path
        assert Settings().client.retry_extra_codes == {420, 500}

        os.unlink(".env")

        monkeypatch.setenv("PREFECT_TEST_MODE", "1")
        monkeypatch.setenv("PREFECT_TESTING_UNIT_TEST_MODE", "1")

        assert Settings().client.retry_extra_codes == set()

    def test_profiles_path_from_toml_source(
        self,
        temporary_toml_file: Callable[[str], None],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        profiles_path = tmp_path / "custom_profiles.toml"

        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)

        profiles_path.write_text(
            textwrap.dedent(
                """
                active = "foo"

                [profiles.foo]
                PREFECT_CLIENT_RETRY_EXTRA_CODES = "420,500"
                """
            )
        )

        temporary_toml_file({"profiles_path": str(profiles_path)})

        assert Settings().profiles_path == profiles_path
        assert Settings().client.retry_extra_codes == {420, 500}

        os.unlink("prefect.toml")

        monkeypatch.setenv("PREFECT_TEST_MODE", "1")
        monkeypatch.setenv("PREFECT_TESTING_UNIT_TEST_MODE", "1")

        assert Settings().client.retry_extra_codes == set()

    def test_profiles_path_from_pyproject_source(
        self,
        temporary_toml_file: Callable[[str], None],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)

        profiles_path = tmp_path / "custom_profiles.toml"
        profiles_path.write_text(
            textwrap.dedent(
                """
                active = "foo"

                [profiles.foo]
                PREFECT_CLIENT_RETRY_EXTRA_CODES = "420,500"
                """
            )
        )

        temporary_toml_file(
            {"tool": {"prefect": {"profiles_path": str(profiles_path)}}},
            path=Path("pyproject.toml"),
        )

        assert Settings().profiles_path == profiles_path
        assert Settings().client.retry_extra_codes == {420, 500}

        os.unlink("pyproject.toml")

        monkeypatch.setenv("PREFECT_TEST_MODE", "1")
        monkeypatch.setenv("PREFECT_TESTING_UNIT_TEST_MODE", "1")

        assert Settings().client.retry_extra_codes == set()

    def test_profiles_path_resolution_order_from_sources(
        self,
        temporary_env_file: Callable[[str], None],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)

        pyproject_profiles_path = tmp_path / "pyproject_profiles.toml"
        pyproject_profiles_path.write_text(
            textwrap.dedent(
                """
                active = "foo"

                [profiles.foo]
                PREFECT_CLIENT_RETRY_EXTRA_CODES = "420,500"
                """
            )
        )

        toml_profiles_path = tmp_path / "toml_profiles.toml"
        toml_profiles_path.write_text(
            textwrap.dedent(
                """
                active = "foo"

                [profiles.foo]
                PREFECT_CLIENT_RETRY_EXTRA_CODES = "300"
                """
            )
        )

        env_profiles_path = tmp_path / "env_profiles.toml"
        env_profiles_path.write_text(
            textwrap.dedent(
                """
                active = "foo"

                [profiles.foo]
                PREFECT_CLIENT_RETRY_EXTRA_CODES = "200"
                """
            )
        )

        with open("pyproject.toml", "w") as f:
            toml.dump(
                {"tool": {"prefect": {"profiles_path": str(pyproject_profiles_path)}}},
                f,
            )

        assert Settings().profiles_path == pyproject_profiles_path
        assert Settings().client.retry_extra_codes == {420, 500}

        with open("prefect.toml", "w") as f:
            toml.dump({"profiles_path": str(toml_profiles_path)}, f)

        assert Settings().profiles_path == toml_profiles_path
        assert Settings().client.retry_extra_codes == {300}

        temporary_env_file(f"PREFECT_PROFILES_PATH={env_profiles_path}")

        assert Settings().profiles_path == env_profiles_path
        assert Settings().client.retry_extra_codes == {200}

        os.unlink(".env")

        assert Settings().profiles_path == toml_profiles_path
        assert Settings().client.retry_extra_codes == {300}

        os.unlink("prefect.toml")

        assert Settings().profiles_path == pyproject_profiles_path
        assert Settings().client.retry_extra_codes == {420, 500}

        os.unlink("pyproject.toml")

        monkeypatch.setenv("PREFECT_TEST_MODE", "1")
        monkeypatch.setenv("PREFECT_TESTING_UNIT_TEST_MODE", "1")

        assert Settings().client.retry_extra_codes == set()

    def test_dot_env_filters_as_expected(
        self,
        temporary_env_file: Callable[[str], None],
    ):
        expected_home = Settings().home
        expected_db_name = Settings().server.database.name
        temporary_env_file("HOME=foo\nNAME=bar")
        assert Settings().home == expected_home
        assert Settings().home != "foo"
        assert Settings().server.database.name == expected_db_name
        assert Settings().server.database.name != "bar"

    def test_environment_variables_take_precedence_over_toml_settings(
        self,
        monkeypatch: pytest.MonkeyPatch,
        temporary_toml_file: Callable[[str], None],
    ):
        """
        Test to ensure that fields with multiple validation aliases respect the
        expected precedence of sources.

        Regression test for https://github.com/PrefectHQ/prefect/issues/15981
        """
        for env_var in os.environ:
            if env_var.startswith("PREFECT_"):
                monkeypatch.delenv(env_var, raising=False)

        monkeypatch.setenv("PREFECT_SERVER_ALLOW_EPHEMERAL_MODE", "false")

        temporary_toml_file({"server": {"ephemeral": {"enabled": "true"}}})

        assert not Settings().server.ephemeral.enabled
        assert not PREFECT_SERVER_ALLOW_EPHEMERAL_MODE.value()

    def test_handle_profile_settings_without_active_profile(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        profiles_path = tmp_path / "profiles.toml"

        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)
        monkeypatch.setenv("PREFECT_PROFILES_PATH", str(profiles_path))

        profiles_path.write_text(
            textwrap.dedent(
                """
                """
            )
        )

        # Should default to ephemeral profile
        assert Settings().server.ephemeral.enabled

    def test_handle_profile_settings_with_invalid_active_profile(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        profiles_path = tmp_path / "profiles.toml"

        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)
        monkeypatch.setenv("PREFECT_PROFILES_PATH", str(profiles_path))

        profiles_path.write_text(
            textwrap.dedent(
                """
                active = "foo"

                [profiles.bar]
                PREFECT_LOGGING_LEVEL = "DEBUG"
                """
            )
        )

        # Should default to ephemeral profile
        assert Settings().server.ephemeral.enabled
        assert Settings().logging.level != "DEBUG"

    def test_handle_profile_settings_with_missing_profile_data(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        profiles_path = tmp_path / "profiles.toml"

        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)
        monkeypatch.setenv("PREFECT_PROFILES_PATH", str(profiles_path))

        profiles_path.write_text(
            textwrap.dedent(
                """
                active = "bar"
                """
            )
        )

        # Should default to ephemeral profile
        assert Settings().server.ephemeral.enabled

    def test_prefect_home_determines_profiles_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """
        this is a regression test for https://github.com/PrefectHQ/prefect/issues/17068

        Verify PREFECT_HOME is used to locate profiles.toml when no explicit
        PREFECT_PROFILES_PATH is set.
        """
        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)

        home_dir = tmp_path / "custom_home"
        home_dir.mkdir()
        profile_path = home_dir / "profiles.toml"
        profile_path.write_text(
            textwrap.dedent(
                """
                active = "test"

                [profiles.test]
                PREFECT_API_KEY = "test_key"
                """
            )
        )

        monkeypatch.setenv("PREFECT_HOME", str(home_dir))
        monkeypatch.delenv("PREFECT_PROFILES_PATH", raising=False)

        assert Settings().home == home_dir
        assert Settings().profiles_path == profile_path
        assert (k := Settings().api.key) and k.get_secret_value() == "test_key"

    def test_prefect_home_and_prefect_profiles_are_both_respected(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """
        Verify that PREFECT_HOME and PREFECT_PROFILES_PATH are both respected when
        both are set, even if PREFECT_PROFILES_PATH is not in the default location
        relative to PREFECT_HOME.
        """
        monkeypatch.delenv("PREFECT_TESTING_TEST_MODE", raising=False)
        monkeypatch.delenv("PREFECT_TESTING_UNIT_TEST_MODE", raising=False)

        home_dir = tmp_path / "custom_home"
        some_other_dir = tmp_path / "some_other_dir"
        home_dir.mkdir()
        some_other_dir.mkdir()
        profile_path = some_other_dir / "profiles.toml"
        profile_path.write_text(
            textwrap.dedent(
                """
                active = "test"

                [profiles.test]
                PREFECT_API_KEY = "test_key"
                """
            )
        )

        monkeypatch.setenv("PREFECT_HOME", str(home_dir))
        monkeypatch.setenv("PREFECT_PROFILES_PATH", str(profile_path))

        assert Settings().home == home_dir
        assert Settings().profiles_path == profile_path
        assert (k := Settings().api.key) and k.get_secret_value() == "test_key"


class TestLoadProfiles:
    @pytest.fixture(autouse=True)
    def temporary_profiles_path(self, tmp_path: Path):
        path = tmp_path / "profiles.toml"
        with temporary_settings(updates={PREFECT_PROFILES_PATH: path}):
            yield path

    def test_load_profiles_no_profiles_file(self):
        assert load_profiles()

    def test_env_variables_respected_when_no_profiles_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """
        Regression test for https://github.com/PrefectHQ/prefect/issues/15981
        """
        for env_var in os.environ:
            if env_var.startswith("PREFECT_"):
                monkeypatch.delenv(env_var, raising=False)

        monkeypatch.setenv("PREFECT_SERVER_ALLOW_EPHEMERAL_MODE", "false")

        # Will be true if the profile is incorrectly taking priority
        assert not Settings().server.ephemeral.enabled
        assert not PREFECT_SERVER_ALLOW_EPHEMERAL_MODE.value()

    def test_load_profiles_missing_ephemeral(
        self,
        temporary_profiles_path: Path,
    ):
        temporary_profiles_path.write_text(
            textwrap.dedent(
                """
                [profiles.foo]
                PREFECT_API_KEY = "bar"
                """
            )
        )
        assert load_profiles()["foo"].settings == {PREFECT_API_KEY: "bar"}
        assert isinstance(load_profiles()["ephemeral"].settings, dict)

    def test_load_profiles_only_active_key(self, temporary_profiles_path: Path):
        temporary_profiles_path.write_text(
            textwrap.dedent(
                """
                active = "ephemeral"
                """
            )
        )
        assert load_profiles().active_name == "ephemeral"
        assert isinstance(load_profiles()["ephemeral"].settings, dict)

    def test_load_profiles_empty_file(self, temporary_profiles_path: Path):
        temporary_profiles_path.touch()
        assert load_profiles().active_name == "ephemeral"
        assert isinstance(load_profiles()["ephemeral"].settings, dict)

    def test_load_profiles_with_ephemeral(self, temporary_profiles_path: Path):
        temporary_profiles_path.write_text(
            """
            [profiles.ephemeral]
            PREFECT_API_KEY = "foo"

            [profiles.bar]
            PREFECT_API_KEY = "bar"
            """
        )
        profiles = load_profiles()
        expected = {
            "ephemeral": {
                PREFECT_API_KEY: "foo",
                PREFECT_SERVER_ALLOW_EPHEMERAL_MODE: "true",  # default value
            },
            "bar": {PREFECT_API_KEY: "bar"},
        }
        for name, settings in expected.items():
            assert profiles[name].settings == settings
            assert profiles[name].source == temporary_profiles_path

    def test_load_profile_ephemeral(self):
        assert load_profile("ephemeral") == Profile(
            name="ephemeral",
            settings={PREFECT_SERVER_ALLOW_EPHEMERAL_MODE: "true"},
            source=DEFAULT_PROFILES_PATH,
        )

    def test_load_profile_missing(self):
        with pytest.raises(ValueError, match="Profile 'foo' not found."):
            load_profile("foo")

    def test_load_profile(self, temporary_profiles_path: Path):
        temporary_profiles_path.write_text(
            textwrap.dedent(
                """
                [profiles.foo]
                PREFECT_API_KEY = "bar"
                PREFECT_DEBUG_MODE = 1
                """
            )
        )
        assert load_profile("foo") == Profile(
            name="foo",
            settings={
                PREFECT_API_KEY: "bar",
                PREFECT_DEBUG_MODE: 1,
            },
            source=temporary_profiles_path,
        )

    def test_load_profile_does_not_allow_nested_data(
        self, temporary_profiles_path: Path
    ):
        temporary_profiles_path.write_text(
            textwrap.dedent(
                """
                [profiles.foo]
                PREFECT_API_KEY = "bar"

                [profiles.foo.nested]
                """
            )
        )
        with pytest.raises(UserWarning, match="Setting 'nested' is not recognized"):
            load_profile("foo")

    def test_load_profile_with_invalid_key(self, temporary_profiles_path):
        temporary_profiles_path.write_text(
            textwrap.dedent(
                """
                [profiles.foo]
                test = "unknown-key"
                """
            )
        )
        with pytest.warns(UserWarning, match="Setting 'test' is not recognized"):
            load_profile("foo")


class TestSaveProfiles:
    @pytest.fixture(autouse=True)
    def temporary_profiles_path(self, tmp_path: Path):
        path = tmp_path / "profiles.toml"
        with temporary_settings(updates={PREFECT_PROFILES_PATH: path}):
            yield path

    def test_save_profiles_does_not_include_default(
        self, temporary_profiles_path: Path
    ):
        """
        Including the default has a tendency to bake in settings the user may not want, and
        can prevent them from gaining new defaults.
        """
        save_profiles(ProfilesCollection(active=None, profiles=[]))
        assert "profiles.default" not in temporary_profiles_path.read_text()

    def test_save_profiles_additional_profiles(self, temporary_profiles_path: Path):
        save_profiles(
            ProfilesCollection(
                profiles=[
                    Profile(
                        name="foo",
                        settings={PREFECT_API_KEY: 1},
                        source=temporary_profiles_path,
                    ),
                    Profile(
                        name="bar",
                        settings={PREFECT_API_KEY: 2},
                        source=temporary_profiles_path,
                    ),
                ],
                active=None,
            )
        )
        assert (
            temporary_profiles_path.read_text()
            == textwrap.dedent(
                """
                [profiles.foo]
                PREFECT_API_KEY = "1"

                [profiles.bar]
                PREFECT_API_KEY = "2"
                """
            ).lstrip()
        )


class TestProfile:
    def test_init_casts_names_to_setting_types(self):
        profile = Profile(name="test", settings={"PREFECT_DEBUG_MODE": 1})  # type: ignore
        assert profile.settings == {PREFECT_DEBUG_MODE: 1}

    def test_validate_settings(self):
        profile = Profile(name="test", settings={PREFECT_SERVER_API_PORT: "foo"})
        with pytest.raises(
            ProfileSettingsValidationError, match="should be a valid integer"
        ):
            profile.validate_settings()

    def test_validate_settings_ignores_environment_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """
        If using `context.use_profile` to validate settings, environment variables may
        override the setting and hide validation errors
        """
        monkeypatch.setenv("PREFECT_SERVER_API_PORT", "1234")
        profile = Profile(name="test", settings={PREFECT_SERVER_API_PORT: "foo"})
        with pytest.raises(
            ProfileSettingsValidationError, match="should be a valid integer"
        ):
            profile.validate_settings()

    def test_validate_settings_nested_field_constraints(self):
        """
        Test that nested field constraints are properly validated.
        Regression test for issue #18258: PREFECT_RUNNER_HEARTBEAT_FREQUENCY validation.
        """
        from prefect.settings import PREFECT_RUNNER_HEARTBEAT_FREQUENCY

        # Test invalid value (< 30)
        profile = Profile(
            name="test", settings={PREFECT_RUNNER_HEARTBEAT_FREQUENCY: "5"}
        )
        with pytest.raises(
            ProfileSettingsValidationError,
            match="Input should be greater than or equal to 30",
        ):
            profile.validate_settings()

        # Test valid value (>= 30)
        profile = Profile(
            name="test", settings={PREFECT_RUNNER_HEARTBEAT_FREQUENCY: "40"}
        )
        # Should not raise
        profile.validate_settings()


class TestProfilesCollection:
    def test_init_stores_single_profile(self):
        profile = Profile(name="test", settings={})
        profiles = ProfilesCollection(profiles=[profile])
        assert profiles.profiles_by_name == {"test": profile}
        assert profiles.active_name is None

    def test_init_stores_multiple_profile(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar])
        assert profiles.profiles_by_name == {"foo": foo, "bar": bar}
        assert profiles.active_name is None

    def test_init_sets_active_name(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar], active="foo")
        assert profiles.active_name == "foo"

    def test_init_sets_active_name_even_if_not_present(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar], active="foobar")
        assert profiles.active_name == "foobar"

    def test_getitem_retrieves_profiles(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar])
        assert profiles["foo"] is foo
        assert profiles["bar"] is bar

    def test_getitem_with_invalid_key(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar])
        with pytest.raises(KeyError):
            profiles["test"]

    def test_iter_retrieves_profile_names(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar])
        assert tuple(sorted(profiles)) == ("bar", "foo")

    def test_names_property(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar], active="foo")
        assert profiles.names == {"foo", "bar"}

    def test_active_profile_property(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar], active="foo")
        assert profiles.active_profile == foo

    def test_active_profile_property_null_active(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar], active=None)
        assert profiles.active_profile is None

    def test_active_profile_property_missing_active(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar], active="foobar")
        with pytest.raises(KeyError):
            profiles.active_profile

    def test_set_active_profile(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar], active=None)
        assert profiles.set_active("foo") is None
        assert profiles.active_name == "foo"
        assert profiles.active_profile is foo

    def test_set_active_profile_with_missing_name(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar], active=None)
        with pytest.raises(ValueError, match="Unknown profile name"):
            profiles.set_active("foobar")

    def test_set_active_profile_with_null_name(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar], active=None)
        assert profiles.set_active(None) is None
        assert profiles.active_name is None
        assert profiles.active_profile is None

    def test_add_profile(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo], active=None)
        assert "bar" not in profiles.names
        profiles.add_profile(bar)
        assert "bar" in profiles.names
        assert profiles["bar"] is bar

    def test_add_profile_already_exists(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar], active=None)
        with pytest.raises(ValueError, match="already exists in collection"):
            profiles.add_profile(bar)

    def test_remove_profiles(self):
        foo = Profile(name="foo", settings={})
        bar = Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo, bar], active=None)
        assert "bar" in profiles
        profiles.remove_profile("bar")
        assert "bar" not in profiles

    def test_remove_profile_does_not_exist(self):
        foo = Profile(name="foo", settings={})
        Profile(name="bar", settings={})
        profiles = ProfilesCollection(profiles=[foo], active=None)
        assert "bar" not in profiles.names
        with pytest.raises(KeyError):
            profiles.remove_profile("bar")

    def test_update_profile_adds_key(self):
        profiles = ProfilesCollection(profiles=[Profile(name="test", settings={})])
        profiles.update_profile(name="test", settings={PREFECT_API_URL: "hello"})
        assert profiles["test"].settings == {PREFECT_API_URL: "hello"}

    def test_update_profile_updates_key(self):
        profiles = ProfilesCollection(profiles=[Profile(name="test", settings={})])
        profiles.update_profile(name="test", settings={PREFECT_API_URL: "hello"})
        assert profiles["test"].settings == {PREFECT_API_URL: "hello"}
        profiles.update_profile(name="test", settings={PREFECT_API_URL: "goodbye"})
        assert profiles["test"].settings == {PREFECT_API_URL: "goodbye"}

    def test_update_profile_removes_key(self):
        profiles = ProfilesCollection(profiles=[Profile(name="test", settings={})])
        profiles.update_profile(name="test", settings={PREFECT_API_URL: "hello"})
        assert profiles["test"].settings == {PREFECT_API_URL: "hello"}
        profiles.update_profile(name="test", settings={PREFECT_API_URL: None})
        assert profiles["test"].settings == {}

    def test_update_profile_mixed_add_and_update(self):
        profiles = ProfilesCollection(profiles=[Profile(name="test", settings={})])
        profiles.update_profile(name="test", settings={PREFECT_API_URL: "hello"})
        assert profiles["test"].settings == {PREFECT_API_URL: "hello"}
        profiles.update_profile(
            name="test",
            settings={PREFECT_API_URL: "goodbye", PREFECT_LOGGING_LEVEL: "DEBUG"},
        )
        assert profiles["test"].settings == {
            PREFECT_API_URL: "goodbye",
            PREFECT_LOGGING_LEVEL: "DEBUG",
        }

    def test_update_profile_retains_existing_keys(self):
        profiles = ProfilesCollection(profiles=[Profile(name="test", settings={})])
        profiles.update_profile(name="test", settings={PREFECT_API_URL: "hello"})
        assert profiles["test"].settings == {PREFECT_API_URL: "hello"}
        profiles.update_profile(name="test", settings={PREFECT_LOGGING_LEVEL: "DEBUG"})
        assert profiles["test"].settings == {
            PREFECT_API_URL: "hello",
            PREFECT_LOGGING_LEVEL: "DEBUG",
        }

    def test_without_profile_source(self):
        foo = Profile(name="foo", settings={}, source=Path("/foo"))
        bar = Profile(name="bar", settings={}, source=Path("/bar"))
        profiles = ProfilesCollection(profiles=[foo, bar], active=None)
        new_profiles = profiles.without_profile_source(Path("/foo"))
        assert new_profiles.names == {"bar"}
        assert profiles.names == {"foo", "bar"}, "Original object not mutated"

    def test_without_profile_source_retains_nulls(self):
        foo = Profile(name="foo", settings={}, source=Path("/foo"))
        bar = Profile(name="bar", settings={}, source=None)
        profiles = ProfilesCollection(profiles=[foo, bar], active=None)
        new_profiles = profiles.without_profile_source(Path("/foo"))
        assert new_profiles.names == {"bar"}
        assert profiles.names == {"foo", "bar"}, "Original object not mutated"

    def test_without_profile_source_handles_null_input(self):
        foo = Profile(name="foo", settings={}, source=Path("/foo"))
        bar = Profile(name="bar", settings={}, source=None)
        profiles = ProfilesCollection(profiles=[foo, bar], active=None)
        new_profiles = profiles.without_profile_source(None)
        assert new_profiles.names == {"foo"}
        assert profiles.names == {"foo", "bar"}, "Original object not mutated"

    def test_equality(self):
        foo = Profile(name="foo", settings={}, source=Path("/foo"))
        bar = Profile(name="bar", settings={}, source=Path("/bar"))

        assert ProfilesCollection(profiles=[foo, bar]) == ProfilesCollection(
            profiles=[foo, bar]
        ), "Same definition should be equal"

        assert ProfilesCollection(
            profiles=[foo, bar], active=None
        ) == ProfilesCollection(profiles=[foo, bar]), (
            "Explicit and implicit null active should be equal"
        )

        assert ProfilesCollection(
            profiles=[foo, bar], active="foo"
        ) != ProfilesCollection(profiles=[foo, bar]), (
            "One null active should be inequal"
        )

        assert ProfilesCollection(
            profiles=[foo, bar], active="foo"
        ) != ProfilesCollection(profiles=[foo, bar], active="bar"), (
            "Different active should be inequal"
        )

        assert ProfilesCollection(profiles=[foo, bar]) == ProfilesCollection(
            profiles=[
                Profile(name="foo", settings={}, source=Path("/foo")),
                Profile(name="bar", settings={}, source=Path("/bar")),
            ]
        ), "Comparison of profiles should use equality not identity"

        assert ProfilesCollection(profiles=[foo, bar]) != ProfilesCollection(
            profiles=[foo]
        ), "Missing profile should be inequal"

        assert ProfilesCollection(profiles=[foo, bar]) != ProfilesCollection(
            profiles=[
                foo,
                Profile(
                    name="bar", settings={PREFECT_API_KEY: "test"}, source=Path("/bar")
                ),
            ]
        ), "Changed profile settings should be inequal"

        assert ProfilesCollection(profiles=[foo, bar]) != ProfilesCollection(
            profiles=[
                foo,
                Profile(name="bar", settings={}, source=Path("/new-path")),
            ]
        ), "Changed profile source should be inequal"


class TestSettingValues:
    @pytest.fixture(autouse=True)
    def clear_env_vars(self, monkeypatch: pytest.MonkeyPatch):
        for env_var in os.environ:
            if env_var.startswith("PREFECT_"):
                monkeypatch.delenv(env_var, raising=False)

    @pytest.fixture(scope="function", params=list(SUPPORTED_SETTINGS.keys()))
    def setting_and_value(self, request: pytest.FixtureRequest) -> tuple[str, Any]:
        setting = request.param
        return setting, SUPPORTED_SETTINGS[setting]["test_value"]

    @pytest.fixture(autouse=True)
    def temporary_profiles_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> Generator[Path, None, None]:
        path = tmp_path / "profiles.toml"
        monkeypatch.setenv("PREFECT_PROFILES_PATH", str(path))
        yield path

    def check_setting_value(
        self,
        setting: str,
        value: Any,
    ):
        # create new root context to pick up the env var changes
        warnings.filterwarnings("ignore", category=UserWarning)
        with prefect.context.root_settings_context():
            field_name = _env_var_to_accessor(setting)
            current_settings = get_current_settings()
            # get value from settings object
            settings_value = get_from_dict(current_settings.model_dump(), field_name)

            if isinstance(settings_value, pydantic.SecretStr):
                settings_value = settings_value.get_secret_value()

            if setting == "PREFECT_LOGGING_EXTRA_LOGGERS":
                assert isinstance(settings_value, list)
                settings_value.sort()
                value.sort()
                assert sorted(settings_value) == sorted(value)
                legacy_value = getattr(prefect.settings, setting).value()
                assert isinstance(legacy_value, list)
                legacy_value.sort()
                assert legacy_value == value
                env_value = current_settings.to_environment_variables(
                    exclude_unset=True
                )[setting]
                assert env_value.split(",") == to_jsonable_python(value)
            elif setting == "PREFECT_CLIENT_CUSTOM_HEADERS":
                # this setting starts as a string and loads as a dictionary
                assert settings_value == json.loads(value)
                # get value from legacy setting object
                assert getattr(prefect.settings, setting).value() == json.loads(value)
            else:
                assert settings_value == value
                # get value from legacy setting object
                assert getattr(prefect.settings, setting).value() == value
                # ensure the value gets added to the environment variables, but "legacy" will use
                # their updated name
                if not SUPPORTED_SETTINGS[setting].get("legacy"):
                    assert current_settings.to_environment_variables(
                        exclude_unset=True
                    )[setting] == _to_environment_variable_value(
                        to_jsonable_python(value)
                    )

    def test_set_via_env_var(
        self,
        setting_and_value: tuple[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ):
        setting, value = setting_and_value

        if (
            setting == "PREFECT_TEST_SETTING"
            or setting == "PREFECT_TESTING_TEST_SETTING"
        ):
            monkeypatch.setenv("PREFECT_TEST_MODE", "True")

        # mock set the env var
        monkeypatch.setenv(setting, _to_environment_variable_value(value))

        self.check_setting_value(setting, value)

    def test_set_via_profile(
        self,
        temporary_profiles_path: Path,
        setting_and_value: tuple[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ):
        setting, value = setting_and_value
        if setting == "PREFECT_PROFILES_PATH":
            pytest.skip("Profiles path cannot be set via a profile")
        if (
            setting == "PREFECT_TEST_SETTING"
            or setting == "PREFECT_TESTING_TEST_SETTING"
        ):
            # PREFECT_TEST_MODE is used to set PREFECT_TEST_SETTING which messes
            # with profile loading
            pytest.skip("Can only set PREFECT_TESTING_TEST_SETTING when in test mode")

        with open(temporary_profiles_path, "w") as f:
            toml.dump(
                {
                    "active": "test",
                    "profiles": {"test": {setting: to_jsonable_python(value)}},
                },
                f,
            )

        self.check_setting_value(setting, value)

    def test_set_via_dot_env_file(
        self,
        setting_and_value: tuple[str, Any],
        temporary_env_file: Callable[[str], None],
        monkeypatch: pytest.MonkeyPatch,
    ):
        setting, value = setting_and_value
        if setting == "PREFECT_PROFILES_PATH":
            monkeypatch.delenv("PREFECT_PROFILES_PATH", raising=False)
        if (
            setting == "PREFECT_TEST_SETTING"
            or setting == "PREFECT_TESTING_TEST_SETTING"
        ):
            monkeypatch.setenv("PREFECT_TEST_MODE", "True")

        temporary_env_file(f"{setting}={_to_environment_variable_value(value)}")

        self.check_setting_value(setting, value)

    def test_set_via_prefect_toml_file(
        self,
        setting_and_value: tuple[str, Any],
        temporary_toml_file: Callable[[dict[str, Any], Path], None],
        monkeypatch: pytest.MonkeyPatch,
    ):
        setting, value = setting_and_value
        if setting == "PREFECT_PROFILES_PATH":
            monkeypatch.delenv("PREFECT_PROFILES_PATH", raising=False)
        if (
            setting == "PREFECT_TEST_SETTING"
            or setting == "PREFECT_TESTING_TEST_SETTING"
        ):
            monkeypatch.setenv("PREFECT_TEST_MODE", "True")

        settings_fields = _get_settings_fields(prefect.settings.Settings)
        toml_dict = {}
        set_in_dict(
            toml_dict, settings_fields[setting].accessor, to_jsonable_python(value)
        )
        temporary_toml_file(toml_dict)

        self.check_setting_value(setting, value)

    def test_set_via_pyproject_toml_file(
        self,
        setting_and_value: tuple[str, Any],
        temporary_toml_file: Callable[[dict[str, Any], Path], None],
        monkeypatch: pytest.MonkeyPatch,
    ):
        setting, value = setting_and_value
        if setting == "PREFECT_PROFILES_PATH":
            monkeypatch.delenv("PREFECT_PROFILES_PATH", raising=False)
        if (
            setting == "PREFECT_TEST_SETTING"
            or setting == "PREFECT_TESTING_TEST_SETTING"
        ):
            monkeypatch.setenv("PREFECT_TEST_MODE", "True")

        settings_fields = _get_settings_fields(prefect.settings.Settings)
        toml_dict = {}
        set_in_dict(
            toml_dict,
            f"tool.prefect.{settings_fields[setting].accessor}",
            to_jsonable_python(value),
        )
        temporary_toml_file(toml_dict, path=Path("pyproject.toml"))

        self.check_setting_value(setting, value)


class TestClientCustomHeadersSetting:
    """Test the PREFECT_CLIENT_CUSTOM_HEADERS setting."""

    def test_default_empty_dict(self):
        """Test that custom headers default to empty dict."""
        from prefect.settings import get_current_settings

        settings = get_current_settings()
        assert settings.client.custom_headers == {}
        assert isinstance(settings.client.custom_headers, dict)

    def test_set_via_temporary_settings(self):
        """Test setting custom headers via temporary_settings."""
        from prefect.settings import get_current_settings

        custom_headers = {
            "X-Test-Header": "test-value",
            "Authorization": "Bearer token123",
        }

        with temporary_settings({PREFECT_CLIENT_CUSTOM_HEADERS: custom_headers}):
            settings = get_current_settings()
            assert settings.client.custom_headers == custom_headers

    def test_json_string_parsing(self, monkeypatch: pytest.MonkeyPatch):
        """Test that JSON string values are parsed correctly."""
        json_value = '{"X-Json-Header": "json-value", "Api-Key": "secret123"}'
        monkeypatch.setenv("PREFECT_CLIENT_CUSTOM_HEADERS", json_value)

        # Create a new settings instance to pick up the env var
        from prefect.settings.models.root import Settings

        settings = Settings()
        expected = {"X-Json-Header": "json-value", "Api-Key": "secret123"}
        assert settings.client.custom_headers == expected

    def test_invalid_json_string_raises_error(self, monkeypatch: pytest.MonkeyPatch):
        """Test that invalid JSON raises appropriate error."""
        monkeypatch.setenv("PREFECT_CLIENT_CUSTOM_HEADERS", "not-valid-json")

        from pydantic_settings.exceptions import SettingsError

        with pytest.raises(SettingsError):
            from prefect.settings.models.root import Settings

            Settings()

    def test_non_string_values_raise_error(self):
        """Test that non-string header values raise validation error."""
        import pydantic

        invalid_headers = {
            "X-Test-Header": 123,  # Integer instead of string
            "X-Another": "valid",
        }

        with pytest.raises(pydantic.ValidationError):
            with temporary_settings({PREFECT_CLIENT_CUSTOM_HEADERS: invalid_headers}):
                from prefect.settings import get_current_settings

                get_current_settings()

    def test_non_string_keys_raise_error(self):
        """Test that non-string header keys raise validation error."""
        import pydantic

        invalid_headers = {
            123: "value",  # Integer key instead of string
            "valid-key": "valid-value",
        }

        with pytest.raises(pydantic.ValidationError):
            with temporary_settings({PREFECT_CLIENT_CUSTOM_HEADERS: invalid_headers}):
                from prefect.settings import get_current_settings

                get_current_settings()

    def test_empty_dict_valid(self):
        """Test that empty dict is valid."""
        from prefect.settings import get_current_settings

        with temporary_settings({PREFECT_CLIENT_CUSTOM_HEADERS: {}}):
            settings = get_current_settings()
            assert settings.client.custom_headers == {}

    def test_unicode_headers_supported(self):
        """Test that unicode values are supported."""
        from prefect.settings import get_current_settings

        unicode_headers = {
            "X-Unicode-Test": "value with émojis 🚀",
            "X-Chinese": "中文测试",
        }

        with temporary_settings({PREFECT_CLIENT_CUSTOM_HEADERS: unicode_headers}):
            settings = get_current_settings()
            assert settings.client.custom_headers == unicode_headers

    def test_case_sensitivity_preserved(self):
        """Test that header name case is preserved."""
        from prefect.settings import get_current_settings

        mixed_case_headers = {
            "X-CamelCase-Header": "value1",
            "lowercase-header": "value2",
            "UPPERCASE-HEADER": "value3",
        }

        with temporary_settings({PREFECT_CLIENT_CUSTOM_HEADERS: mixed_case_headers}):
            settings = get_current_settings()
            assert settings.client.custom_headers == mixed_case_headers
