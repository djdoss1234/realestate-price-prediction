"""
Airflow DAG: 매주 월요일 통계청/ECOS/청약/기상 데이터 업데이트
================================================================
스케줄: 매주 월요일 03:00 KST
"""

from datetime import datetime, timedelta
import os, sys

sys.path.insert(0, os.getenv("REALESTATE_HOME", "/Users/kimminseok/Desktop/realestate"))

from airflow import DAG
from airflow.operators.python import PythonOperator

SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL", "")
DB_PATH       = os.getenv("REALESTATE_DB", "/Users/kimminseok/Desktop/realestate/realestate.db")


def _slack_alert(context):
    if not SLACK_WEBHOOK:
        return
    import requests
    task = context.get("task_instance")
    requests.post(SLACK_WEBHOOK, json={
        "text": (f":red_circle: *Weekly Stats 실패*\n"
                 f"Task: `{task.task_id}` | {context['execution_date']}\n"
                 f"로그: {task.log_url}")
    }, timeout=10)


default_args = {
    "owner":            "realestate",
    "retries":          2,
    "retry_delay":      timedelta(minutes=30),
    "on_failure_callback": _slack_alert,
}


def collect_kosis():
    from collectors.kosis_collector import KosisCollector
    c = KosisCollector(db_path=DB_PATH)
    result = c.collect_all(start_year=2020)
    print("KOSIS 수집:", result)

def collect_ecos():
    from collectors.ecos_collector import EcosCollector
    c = EcosCollector(db_path=DB_PATH)
    result = c.collect(start_ym="202001")
    print("ECOS 수집:", result)

def collect_subscription():
    from collectors.subscription_collector import SubscriptionCollector
    c = SubscriptionCollector(db_path=DB_PATH)
    result = c.collect_all(start_ym="202301")
    print("청약 수집:", result)

def collect_weather():
    from collectors.weather_collector import WeatherCollector
    c = WeatherCollector(db_path=DB_PATH)
    result = c.collect_all(start_date="20230101")
    print("기상 수집:", result)

def collect_land_price():
    from collectors.land_price_collector import LandPriceCollector
    c = LandPriceCollector(db_path=DB_PATH)
    result = c.collect_all_sgg(base_year=2024)
    print("공시지가 수집:", result)

def collect_schools():
    from collectors.school_collector import SchoolCollector
    c = SchoolCollector(db_path=DB_PATH)
    result = c.collect_all(year=2023)
    print("학교 수집:", result)

def collect_unsold():
    from collectors.unsold_house_collector import UnsoldHouseCollector
    from datetime import datetime
    c = UnsoldHouseCollector(db_path=DB_PATH)
    # 최근 3개월 수집
    from dateutil.relativedelta import relativedelta
    now = datetime.now()
    start = (now - relativedelta(months=3)).strftime("%Y%m")
    result = c.collect_range(start_ym=start)
    print("미분양 수집:", result)

def collect_building_registry():
    from collectors.building_registry_collector import BuildingRegistryCollector
    c = BuildingRegistryCollector(db_path=DB_PATH)
    # 거래 DB의 (sggCd, umdCd) 쌍 기반 자동 수집
    result = c.collect_all()
    print("건축물대장 수집:", result)


def notify_success(context):
    if not SLACK_WEBHOOK:
        return
    import requests
    requests.post(SLACK_WEBHOOK, json={
        "text": f":chart_with_upwards_trend: 주간 통계 업데이트 완료 ({context['execution_date'].strftime('%Y-%m-%d')})"
    }, timeout=10)


with DAG(
    dag_id="weekly_stats_update",
    description="매주 월요일 통계청·ECOS·청약·기상·공시지가·학교 데이터 업데이트",
    schedule="0 3 * * 1",      # 매주 월요일 03:00
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["realestate", "stats", "weekly"],
    on_success_callback=notify_success,
) as dag:

    t_kosis = PythonOperator(
        task_id="collect_kosis",
        python_callable=collect_kosis,
        execution_timeout=timedelta(hours=1),
    )

    t_ecos = PythonOperator(
        task_id="collect_ecos",
        python_callable=collect_ecos,
        execution_timeout=timedelta(minutes=30),
    )

    t_sub = PythonOperator(
        task_id="collect_subscription",
        python_callable=collect_subscription,
        execution_timeout=timedelta(hours=1),
    )

    t_weather = PythonOperator(
        task_id="collect_weather",
        python_callable=collect_weather,
        execution_timeout=timedelta(hours=1),
    )

    t_land_price = PythonOperator(
        task_id="collect_land_price",
        python_callable=collect_land_price,
        execution_timeout=timedelta(hours=2),
    )

    t_school = PythonOperator(
        task_id="collect_schools",
        python_callable=collect_schools,
        execution_timeout=timedelta(hours=2),
    )

    t_unsold = PythonOperator(
        task_id="collect_unsold",
        python_callable=collect_unsold,
        execution_timeout=timedelta(hours=1),
    )

    t_bldg = PythonOperator(
        task_id="collect_building_registry",
        python_callable=collect_building_registry,
        execution_timeout=timedelta(hours=4),
    )

    # 독립 병렬 수집
    [t_kosis, t_ecos, t_sub, t_weather, t_land_price, t_school, t_unsold, t_bldg]
