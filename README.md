# 급식 식사 관리 시스템

Flask와 SQLite로 학생 UID와 급식 이용 기록을 관리합니다. 기본 출입 흐름은
ESP32/MFRC522가 아니라 `android/`의 태블릿 카메라 QR/바코드 앱입니다.

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

## Android 태블릿 앱 (기본 사용 경로)

`android/`를 Android Studio에서 열고 Gradle 동기화 후 태블릿 또는 카메라가 있는 Android
기기에서 `app`을 실행합니다. 앱은 Google ML Kit Barcode Scanning으로 QR/바코드를 읽고,
문자열을 학생 UID로 사용해 `POST /api/meal/scan`에 전송합니다. 카메라 권한을 허용하고
화면의 서버 주소를 저장하면 승인·중복·미등록·배식 시간 오류를 한국어로 표시합니다.
같은 UID의 연속 인식은 앱에서 잠시 무시하며, 서버의 당일 중복 검증도 그대로 적용됩니다.

### 설치 및 실행 순서

1. 라즈베리파이와 태블릿을 같은 Wi-Fi에 연결합니다.
2. 라즈베리파이에서 프로젝트를 설치하고 서버를 실행합니다.
   `flask --app app:create_app run --host 0.0.0.0 --port 5000`
3. Android Studio에서 `android/`를 열어 태블릿에 `app`을 설치합니다.
4. 앱 서버 주소에 라즈베리파이의 사설 IP를 입력합니다(예:
   `http://192.168.1.10:5000`). 주소는 기기에 저장됩니다. 개발용 HTTP를 허용하므로
   신뢰할 수 있는 내부망에서만 사용하고, 운영에서는 HTTPS를 사용하세요.

### 학생 QR 코드 값 규칙

QR/바코드의 원시 문자열 전체가 UID가 됩니다. 예를 들어 QR 값이 `ABC123`이면 먼저
`POST /api/students`에 `{"uid":"ABC123","grade":3,"class":2}`로 학생을 등록해야 합니다.
앞뒤 공백은 서버에서 제거되지만, 대소문자와 나머지 문자는 등록값과 정확히 일치해야 합니다.
QR 내용에 이름·주민번호 등 불필요한 개인정보를 넣지 마세요.

### 기존 Arduino 스케치

`arduino/meal_reader.ino`는 호환성을 위해 남겨 둔 이전 ESP32/MFRC522 예제이며 더 이상
기본 경로가 아닙니다. 새 설치는 Android 태블릿 앱을 사용하세요. 스케치를 계속 사용할
경우에만 Wi-Fi와 서버 주소를 설정합니다. MFRC522: SS=GPIO5, RST=GPIO4, SCK=18,
MOSI=23, MISO=19. SSD1306 I2C: SDA=21, SCL=22. 부저는 GPIO27입니다.

## 보안 및 운영

개발용 서버를 인터넷에 직접 노출하지 말고 HTTPS 역방향 프록시와 방화벽을 사용하세요. 운영에서는 `flask run` 대신 Gunicorn/uWSGI를 사용하고, `SECRET_KEY`·Wi-Fi·서버 주소를 환경변수/비밀 저장소로 관리하며 코드에 커밋하지 마세요. UID는 개인정보로 취급하고 접근 로그·백업 파일을 보호하며 관리자 인증, rate limiting, 입력 감사와 정기 백업을 추가하세요. SQLite는 단일 서버/소규모 환경에 적합하며 규모가 커지면 PostgreSQL로 이전하세요.
