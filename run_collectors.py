"""
수집기 실행 스크립트
usage: python3 run_collectors.py [ecos|kosis|kakao|all]
"""
import os, sys, logging

def _load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"\''))

_load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("run_collectors.log", "a", "utf-8"),
    ],
)
log = logging.getLogger(__name__)


def run_ecos():
    from collectors.ecos_collector import EcosCollector
    log.info("=== ECOS 수집 시작 ===")
    c = EcosCollector()
    n = c.collect(start_ym="202001")
    log.info("ECOS 완료: %d건", n)
    return n


def run_kosis():
    from collectors.kosis_collector import KosisCollector
    log.info("=== KOSIS 수집 시작 ===")
    c = KosisCollector()
    result = c.collect_all(start_year=2020)
    log.info("KOSIS 완료: %s", result)
    return result


def run_apartment_complex():
    from collectors.apartment_complex_collector import ApartmentComplexCollector
    log.info("=== 공동주택단지 수집 시작 ===")
    c = ApartmentComplexCollector()
    result = c.collect_all()
    log.info("공동주택단지 완료: %s", result)
    return result


def run_building_registry():
    from collectors.building_registry_collector import BuildingRegistryCollector
    log.info("=== 건축물대장 수집 시작 ===")
    c = BuildingRegistryCollector()
    result = c.collect_all()
    log.info("건축물대장 완료: %s", result)
    return result


def run_subscription():
    from collectors.subscription_collector import SubscriptionCollector
    log.info("=== 청약정보 수집 시작 ===")
    c = SubscriptionCollector()
    result = c.collect_all(start_ym="202001")
    log.info("청약정보 완료: %s", result)
    return result


def run_weather():
    from collectors.weather_collector import WeatherCollector
    log.info("=== 기상특보 수집 시작 (최근 6일) ===")
    c = WeatherCollector()
    result = c.collect_all()   # 기본값: 오늘 기준 6일 이내
    log.info("기상특보 완료: %s", result)
    return result


def run_academy():
    from collectors.academy_collector import AcademyCollector
    log.info("=== NEIS 학원정보 수집 시작 ===")
    c = AcademyCollector()
    result = c.collect_all()
    log.info("학원정보 완료: %s", result)
    return result


def run_seoul_population():
    from collectors.seoul_population_collector import SeoulPopulationCollector
    log.info("=== 서울 생활인구 수집 시작 ===")
    c = SeoulPopulationCollector()
    n = c.collect_latest()
    log.info("서울 생활인구 완료: %d건", n)
    return n


def run_commercial_district():
    from collectors.commercial_district_collector import CommercialDistrictCollector
    log.info("=== 소상공인 상가정보 수집 시작 ===")
    c = CommercialDistrictCollector()
    result = c.collect_all()
    log.info("상가정보 완료: %s", result)
    return result


def run_lh_rental():
    from collectors.lh_rental_collector import LhRentalCollector
    log.info("=== LH 공공임대주택 수집 시작 ===")
    c = LhRentalCollector()
    result = c.collect_all(start_ym="202001")
    log.info("LH임대 완료: %s", result)
    return result


def run_crime():
    from collectors.crime_collector import CrimeCollector
    log.info("=== 범죄통계 수집 시작 ===")
    c = CrimeCollector()
    result = c.collect_all(start_year=2020)
    log.info("범죄통계 완료: %s", result)
    return result


def run_apt_complex_identity():
    from collectors.apt_complex_identity_collector import AptComplexIdentityCollector
    log.info("=== 공동주택 단지식별정보 수집 시작 ===")
    c = AptComplexIdentityCollector()
    result = c.collect_all()
    log.info("단지식별 완료: %s", result)
    return result


def run_school():
    from collectors.school_collector import SchoolCollector
    log.info("=== 학교 수집 시작 ===")
    c = SchoolCollector()
    result = c.collect_all()
    log.info("학교 완료: %s", result)
    return result


def run_land_price():
    from collectors.land_price_collector import LandPriceCollector
    log.info("=== 공시지가(거래가 프록시) 수집 시작 ===")
    c = LandPriceCollector()
    result = c.build_from_transactions(start_year=2020)
    log.info("공시지가 완료: %s건", result)
    return result


def run_unsold_house():
    from collectors.unsold_house_collector import UnsoldHouseCollector
    log.info("=== 미분양주택현황 수집 시작 ===")
    c = UnsoldHouseCollector()
    result = c.collect_range(start_ym="202001")
    log.info("미분양 완료: %s", result)
    return result


def run_kakao(limit: int = 5000):
    from collectors.kakao_poi_collector import KakaoPOICollector
    log.info("=== Kakao POI 수집 시작 (최대 %d건) ===", limit)
    c = KakaoPOICollector()
    results = c.collect_from_db(limit=limit)
    log.info("Kakao POI 완료: %d건", len(results))
    return len(results)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    limit  = int(sys.argv[2]) if len(sys.argv) > 2 else 5000

    if target in ("ecos", "all"):
        run_ecos()

    if target in ("kosis", "all"):
        run_kosis()

    if target in ("apt_complex", "all"):
        run_apartment_complex()

    if target in ("building", "all"):
        run_building_registry()

    if target in ("subscription", "all"):
        run_subscription()

    if target in ("weather", "all"):
        run_weather()

    if target in ("academy", "all"):
        run_academy()

    if target in ("seoul_pop", "all"):
        run_seoul_population()

    if target in ("commercial", "all"):
        run_commercial_district()

    if target in ("lh_rental", "all"):
        run_lh_rental()

    if target in ("crime", "all"):
        run_crime()

    if target in ("apt_identity", "all"):
        run_apt_complex_identity()

    if target in ("school", "all"):
        run_school()

    if target in ("land_price", "all"):
        run_land_price()

    if target in ("unsold", "all"):
        run_unsold_house()

    if target in ("kakao", "all"):
        run_kakao(limit=limit)
