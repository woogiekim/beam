# Beam

**터미널 UI 기반 SSH/SFTP 파일 배포 도구**

Beam은 SSH 서버에 파일을 빠르고 안전하게 배포하기 위한 터미널 UI(TUI) 애플리케이션입니다. 마우스 없이 키보드만으로 로컬 파일을 선택해 원격 서버에 업로드하고, 필요 시 이전 상태로 즉시 롤백할 수 있습니다.

---

## 주요 기능

- **워크스페이스 관리** — 여러 서버(개발/스테이징/프로덕션 등)를 워크스페이스로 저장하고 전환
- **사이드-바이-사이드 파일 뷰** — 로컬 파일과 원격 파일을 한 화면에 나란히 표시
- **Diff 인디케이터** — 로컬 파일에 `+`(신규) / `M`(변경됨) 태그를 실시간으로 표시
- **다중 파일 선택 배포** — Space로 개별 선택, Ctrl+A로 전체 선택 후 한 번에 업로드
- **원격 파일 삭제** — 원격 패널에서 파일을 선택해 직접 삭제
- **세션 롤백** — 배포 전 자동 스냅샷을 찍어 언제든 이전 버전으로 복원 가능
- **Diff 임계값 경고** — 로컬-원격 파일 구성 차이가 설정 임계값을 초과하면 경고 알림
- **SSH 키 / 비밀번호 인증** 모두 지원
- **사용자 정의 포트** — 기본값 22 이외의 포트 설정 가능

---

## 요구 사항

| 항목 | 버전 |
|---|---|
| Python | 3.9 이상 |
| pipx | 최신 권장 (설치 스크립트가 자동 처리) |
| SSH 접근 | 원격 서버에 SFTP 서브시스템이 활성화되어 있어야 함 |

> **참고**: 원격 서버가 SSH를 통한 SFTP 접속을 허용해야 합니다. 대부분의 Linux 서버에서 기본으로 활성화되어 있습니다.

---

## 설치 방법

### 방법 1 — 원터치 설치 (권장)

아래 명령어 한 줄로 설치가 완료됩니다. pipx가 없어도 자동으로 설치해 줍니다.

```bash
curl -s https://raw.githubusercontent.com/woogiekim/beam/main/install.sh | bash
```

설치 후 새 셸을 열거나 아래 명령을 실행하면 바로 사용할 수 있습니다:

```bash
export PATH="$HOME/.local/bin:$PATH"
beam
```

### 방법 2 — 로컬 저장소에서 설치

저장소를 직접 클론한 후 설치 스크립트를 실행합니다:

```bash
git clone https://github.com/woogiekim/beam.git
cd beam
./install.sh
```

### 방법 3 — pip으로 직접 설치

```bash
pip install -e .
```

또는 가상 환경을 직접 관리하는 경우:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
beam
```

---

## 사용법

### 실행

```bash
beam
```

### 기본 워크플로

1. **워크스페이스 선택 화면**이 열립니다.
2. `Ctrl+N`으로 새 워크스페이스를 추가합니다.
3. 워크스페이스를 선택하고 `Enter`를 눌러 접속합니다.
4. 파일 선택 화면에서 로컬(왼쪽)과 원격(오른쪽) 파일을 확인합니다.
5. 로컬 패널에서 `Space`로 파일을 선택한 후 `Ctrl+U`로 배포합니다.
6. 배포를 취소하거나 이전 상태로 돌아가려면 `Ctrl+R`로 롤백 패널을 엽니다.

### 단축키 목록

#### 워크스페이스 화면

| 단축키 | 동작 |
|---|---|
| `Ctrl+N` | 워크스페이스 추가 |
| `Ctrl+E` | 워크스페이스 편집 |
| `Ctrl+D` | 워크스페이스 삭제 |
| `Enter` | 워크스페이스 열기 (접속) |

#### 파일 선택 화면

| 단축키 | 동작 |
|---|---|
| `Space` | 파일 선택/해제 (로컬 또는 원격 패널) |
| `Ctrl+A` | 로컬 파일 전체 선택 / 전체 해제 |
| `Ctrl+U` | 선택한 로컬 파일을 원격에 배포 |
| `Ctrl+D` | 선택한 원격 파일 삭제 (원격 패널 포커스 시) |
| `Ctrl+R` | 롤백 패널 열기 / 선택 파일 롤백 실행 |
| `F5` | 파일 목록 새로고침 |
| `Esc` | 뒤로 가기 / 롤백 패널 닫기 |
| `Ctrl+Q` | 앱 종료 |

#### 워크스페이스 폼 화면

| 단축키 | 동작 |
|---|---|
| `Ctrl+S` | 저장 |
| `Esc` | 취소 |

### 파일 상태 표시

로컬 패널의 각 파일 앞에 상태 태그가 표시됩니다:

| 태그 | 의미 |
|---|---|
| `+` (초록) | 원격에 없는 신규 파일 |
| `M` (노랑) | 원격 파일과 크기가 다른 변경 파일 |
| (태그 없음) | 원격 파일과 동일 |

---

## 설정

설정 파일은 `~/.beam/workspaces.json`에 저장됩니다.
직접 편집하거나 TUI 내에서 워크스페이스를 추가/편집하면 자동으로 업데이트됩니다.

### 워크스페이스 설정 항목

| 항목 | 필수 | 설명 | 기본값 |
|---|---|---|---|
| `name` | 필수 | 워크스페이스 식별 이름 | — |
| `local_root` | 필수 | 로컬 프로젝트 루트 디렉터리 절대 경로 | — |
| `host` | 필수 | 원격 서버 호스트명 또는 IP | — |
| `user` | 필수 | SSH 접속 사용자명 | — |
| `remote_root` | 필수 | 원격 서버의 배포 대상 절대 경로 (`/`로 시작) | — |
| `port` | 선택 | SSH 포트 | `22` |
| `password` | 조건부 | SSH 비밀번호 (`key_path` 없을 때 필수) | — |
| `key_path` | 조건부 | SSH 개인키 경로 (`password` 없을 때 필수) | — |
| `diff_threshold` | 선택 | 로컬-원격 파일 구성 차이 경고 임계값 (0.0 ~ 1.0) | `0.30` |

> `password`와 `key_path` 중 하나는 반드시 설정해야 합니다.

### 설정 파일 예시

```json
{
  "workspaces": [
    {
      "name": "production",
      "local_root": "/home/me/myproject",
      "host": "server.example.com",
      "port": 22,
      "user": "deploy",
      "password": null,
      "key_path": "~/.ssh/id_rsa",
      "remote_root": "/var/www/myproject",
      "diff_threshold": 0.3
    },
    {
      "name": "staging",
      "local_root": "/home/me/myproject",
      "host": "staging.example.com",
      "port": 2222,
      "user": "deploy",
      "password": "my-secret",
      "key_path": null,
      "remote_root": "/srv/staging",
      "diff_threshold": 0.5
    }
  ]
}
```

### `diff_threshold` 상세 설명

로컬과 원격 디렉터리 구성의 불일치 비율이 이 값을 초과하면 배포 전 경고 알림이 표시됩니다.

- `0.0` — 파일 하나라도 차이가 있으면 경고
- `0.30` (기본값) — 30% 이상 차이가 나면 경고
- `1.0` — 경고 비활성화

실수로 잘못된 디렉터리에 배포하는 것을 방지하는 안전장치입니다.

---

## 개발 환경 설정

기여하거나 직접 수정하고 싶다면 아래 방법으로 개발 환경을 구성할 수 있습니다.

```bash
git clone https://github.com/woogiekim/beam.git
cd beam
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"   # dev extras가 있는 경우
beam
```

### 프로젝트 구조

```
beam/
├── beam/
│   ├── app.py        # TUI 앱 진입점 및 모든 화면 정의
│   ├── config.py     # 워크스페이스 설정 로드/저장 (WorkspaceConfig)
│   ├── diff.py       # 로컬-원격 디렉터리 diff 계산
│   ├── rollback.py   # 세션 내 롤백 스냅샷 관리
│   └── sftp.py       # paramiko 기반 SFTP 클라이언트 래퍼
├── install.sh        # 원터치 설치 스크립트 (pipx 기반)
└── pyproject.toml    # 패키지 메타데이터 및 의존성
```

### 주요 의존성

| 패키지 | 용도 |
|---|---|
| [textual](https://github.com/Textualize/textual) | 터미널 UI 프레임워크 |
| [paramiko](https://www.paramiko.org/) | SSH/SFTP 클라이언트 |

---

## 라이선스

이 프로젝트의 라이선스는 저장소를 확인하세요.
