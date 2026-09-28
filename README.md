# 급식 식사 관리 시스템

Flask와 SQLite로 학생 RFID(UID)와 급식 이용 기록을 관리하는 초기 프로젝트입니다.

## 설치 및 실행

Python 3.10+에서 실행합니다.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask --app app:create_app run --host 0.0.0.0 --port 5000
pytest
```

`MEAL_TIMEZONE` 환경변수는 IANA 시간대이며 기본값은 `Asia/Seoul`입니다. SQLite 파일은 `instance/meals.sqlite3`에 자동 생성됩니다.

## API

- `POST /api/students` `{ "uid":"A1", "grade":3, "class":2 }` 등록
- `GET /api/students` 학생 목록
- `POST /api/schedules` `{ "date":"2026-09-28", "meal_type":"lunch", "grade":3, "class":2, "starts_at":"11:30", "ends_at":"13:30" }` (학년·반별 일정)
- `GET /api/schedules?date=YYYY-MM-DD` 일정 조회
- `POST /api/meal/scan` `{ "uid":"A1" }` 태그 검증 및 기록
- `GET /api/meals/today` 오늘 기록

태그 응답 코드는 `unregistered_card`(등록되지 않은 카드), `before_meal_time`, `after_meal_time`, `duplicate_same_day`, `approved`이며 HTTP 상태 코드도 함께 제공합니다. 검증 순서는 등록 → 학생의 학년·반에 해당하는 당일 일정과 시간 → 당일 중복 → 기록 저장입니다.

## ESP32 배선

`arduino/meal_reader.ino`에 Wi-Fi와 서버 주소를 설정합니다. MFRC522: SS=GPIO5, RST=GPIO4, SCK=18, MOSI=23, MISO=19. SSD1306 I2C: SDA=21, SCL=22. 부저는 GPIO27입니다. ESP32 Arduino Library Manager에서 MFRC522, Adafruit GFX, Adafruit SSD1306을 설치하세요.

## 보안 및 운영

개발용 서버를 인터넷에 직접 노출하지 말고 HTTPS 역방향 프록시와 방화벽을 사용하세요. 운영에서는 `flask run` 대신 Gunicorn/uWSGI를 사용하고, `SECRET_KEY`·Wi-Fi·서버 주소를 환경변수/비밀 저장소로 관리하며 코드에 커밋하지 마세요. UID는 개인정보로 취급하고 접근 로그·백업 파일을 보호하며 관리자 인증, rate limiting, 입력 감사와 정기 백업을 추가하세요. SQLite는 단일 서버/소규모 환경에 적합하며 규모가 커지면 PostgreSQL로 이전하세요.
