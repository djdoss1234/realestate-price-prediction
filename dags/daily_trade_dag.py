"""
Airflow DAG: 매일 새벽 2시 실거래가 자동 수집
===============================================
실행 환경:
  pip install apache-airflow==2.10.4  (Python 3.12 권장, 3.13 미지원)
  airflow db init
  airflow users create --role Admin --username admin ...
  airflow webserver & airflow scheduler

환경변수 (Airflow UI → Admin → Variables 또는 .env):
  MOLIT_API_KEY, SLACK_WEBHOOK_URL, AIRFLOW_HOME
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.slack.notifications.slack_webhook import SlackWebhookNotifier

import os, sys
sys.path.insert(0, os.getenv("REALESTATE_HOME", "/Users/kimminseok/Desktop/realestate"))

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL", "")
DB_PATH       = os.getenv("REALESTATE_DB", "/Users/kimminseok/Desktop/realestate/realestate.db")


def _slack_alert(context):
    if not SLACK_WEBHOOK:
        return
    import requests
    task = context.get("task_instance")
    msg  = (f":red_circle: *Task 실패*\n"
            f"DAG: `{context['dag'].dag_id}`\n"
            f"Task: `{task.task_id}`\n"
            f"실행시간: `{context['execution_date']}`\n"
            f"로그: {task.log_url}")
    requests.post(SLACK_WEBHOOK, json={"text": msg}, timeout=10)


default_args = {
    "owner":            "realestate",
    "retries":          3,
    "retry_delay":      timedelta(minutes=10),
    "on_failure_callback": _slack_alert if SLACK_WEBHOOK else None,
}


def collect_apt_trade():
    from molit_collector import Config, MolitCollector
    cfg = Config(api_key=os.getenv("MOLIT_API_KEY", ""))
    c   = MolitCollector(cfg, db_path=DB_PATH)
    c.collect(trade_types=["아파트_매매", "아파트_전월세"])
    c.close()

def collect_villa_trade():
    from molit_collector import Config, MolitCollector
    cfg = Config(api_key=os.getenv("MOLIT_API_KEY", ""))
    c   = MolitCollector(cfg, db_path=DB_PATH)
    c.collect(trade_types=["연립다세대_매매", "연립다세대_전월세"])
    c.close()

def collect_land_trade():
    from morning_collect import log
    from molit_collector import Config, MolitCollector
    cfg = Config(api_key=os.getenv("MOLIT_API_KEY", ""))
    c   = MolitCollector(cfg, db_path=DB_PATH)
    c.collect(trade_types=["토지_매매"])
    c.close()

def retrain_models():
    """주간 재학습 (토요일에만 실행)"""
    if datetime.now().weekday() != 5:  # 토요일만
        print("재학습 스킵 (토요일 아님)")
        return
    import subprocess
    result = subprocess.run(
        [sys.executable, "/Users/kimminseok/Desktop/realestate/realestate_ml.py"],
        capture_output=True, text=True, timeout=7200,
        cwd="/Users/kimminseok/Desktop/realestate"
    )
    if result.returncode != 0:
        raise RuntimeError(f"재학습 실패:\n{result.stderr[-500:]}")
    print(result.stdout[-500:])

def slack_success(context):
    if not SLACK_WEBHOOK:
        return
    import requests
    requests.post(SLACK_WEBHOOK, json={
        "text": f":white_check_mark: 실거래 수집 완료 ({context['execution_date'].strftime('%Y-%m-%d')})"
    }, timeout=10)


with DAG(
    dag_id="daily_trade_collect",
    description="매일 새벽 2시 실거래가 자동 수집",
    schedule="0 2 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["realestate", "collection"],
    on_success_callback=slack_success,
) as dag:

    t_apt = PythonOperator(
        task_id="collect_apt_trade",
        python_callable=collect_apt_trade,
        execution_timeout=timedelta(hours=2),
    )

    t_villa = PythonOperator(
        task_id="collect_villa_trade",
        python_callable=collect_villa_trade,
        execution_timeout=timedelta(hours=1),
    )

    t_land = PythonOperator(
        task_id="collect_land_trade",
        python_callable=collect_land_trade,
        execution_timeout=timedelta(hours=2),
    )

    t_retrain = PythonOperator(
        task_id="retrain_models",
        python_callable=retrain_models,
        execution_timeout=timedelta(hours=3),
    )

    # 병렬 수집 → 완료 후 재학습
    [t_apt, t_villa, t_land] >> t_retrain
