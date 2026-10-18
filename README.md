# Beefington prepared-post publisher

추가 AI API 비용 없이, 이 채팅에서 미리 만든 이미지만 예약 게시합니다.
GitHub가 새 이미지를 만들거나 최신 밈을 조사하지는 않습니다.

## 현재 상태

- 게시 활성화 전: `PUBLISH_ENABLED`는 설정하지 않습니다.
- `queue.json`은 비어 있습니다. 이미 게시한 비행기 밈은 재게시하지 않습니다.
- GitHub/Meta 인증 및 실제 클라우드 게시 테스트는 아직 필요합니다.
- 로컬 Codex 자동화는 클라우드 게시 검증 후 중지합니다.

## 운영

공개 저장소, 기본 `ubuntu-latest` runner, 하루 5회 짧은 실행만 사용합니다.
유료 AI API, 외부 호스팅, artifact/cache 저장, 큰 runner는 사용하지 않습니다.
저장소가 비공개로 변경되면 게시를 거부합니다. 저장소 운영자가 GitHub 유료 기능을
별도로 켜면 비용이 생길 수 있으므로 변경하지 않습니다.

목표 시간은 한국 시간 09·12·15·18·21시입니다. GitHub 실행은 지연되거나 누락될 수 있습니다.
90분 넘게 늦어진 항목은 건너뛰며 과거 분량을 몰아 올리지 않습니다.
공개 저장소는 60일간 활동이 없으면 예약 실행이 자동 비활성화될 수 있습니다.

## 최초 연결

1. Meta 개발자 앱에서 **Instagram API with Instagram Login**을 구성합니다.
2. `@mr.sirbeefington` 전문 계정을 연결하고 기본 조회/콘텐츠 게시 권한을 승인합니다.
   기본 권한 이름은 `instagram_business_basic`, `instagram_business_content_publish`입니다.
3. 장기 토큰과 Instagram 사용자 ID를 저장소 Settings → Secrets and variables → Actions에
   `IG_ACCESS_TOKEN`, `IG_USER_ID`라는 Secrets로 직접 저장합니다. 채팅이나 코드에 쓰지 않습니다.
4. 토큰은 만료되므로 Meta가 표시하는 만료일을 기록하고 만료 전에 갱신해야 합니다.
   이 초안에는 자동 갱신을 넣지 않았습니다. 만료 시 실행은 실패하며 게시하지 않습니다.
5. Queue를 준비하고 Actions에서 `publish=false`로 검증합니다.
6. 사용자 확인 후 Repository variable `PUBLISH_ENABLED=true`로 활성화하고 한 건을 시험합니다.
7. Instagram에 실제 게시된 결과를 확인한 뒤 기존 Codex 예약을 중지합니다.

## Queue 형식

```json
[
  {
    "id": "2026-10-19-09",
    "scheduled_at": "2026-10-19T09:00:00+09:00",
    "approved": true,
    "image": "media/2026-10-19-09.jpg",
    "sha256": "<실제 JPEG 파일 SHA-256>",
    "caption": "English caption. #AIGenerated",
    "sources": [
      {"url": "https://실제-밈-확산-근거", "observed_at": "2026-10-18T12:00:00+09:00"}
    ]
  }
]
```

이미지는 1080×1350 JPEG로 준비합니다. 기준 캐릭터 이미지는 이 공개 저장소에 넣지 않습니다.
실제 게시 예정 이미지와 영어 캡션 및 근거 링크만 넣습니다. 공개 저장소이므로 사전 공개됩니다.
게시 시점을 기준으로 근거 날짜가 7일 이내인 항목만 처리합니다. 오래된 밈을 최신으로
만들기 위해 날짜를 바꾸지 않습니다. 준비된 항목이 떨어지면 게시하지 않습니다.

## 중복 및 장애 처리

네트워크 요청 전 의도를 `state.json`에 먼저 기록합니다. 게시 결과가 불명확하면 자동으로
재시도하지 않으며 이후 게시도 멈춥니다. Instagram과 Actions 결과를 확인해 복구합니다.
`published` 또는 불명확 상태의 항목을 삭제하면 중복 게시 위험이 있습니다.
AI 콘텐츠 표시를 요청하며, 해당 필드를 API가 거절하면 표시 없이 재시도하지 않습니다.

## 로컬 검증 (네트워크·과금 없음)

```sh
python -m unittest test_publisher -v
python publisher.py
```

## 공식 참고

- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login

비밀정보를 공개 저장소나 실행 로그에 넣지 않습니다. 스크립트는 토큰을 읽어 인증에만 쓰고
API 오류 응답 본문이나 토큰이 포함될 수 있는 URL은 출력하지 않습니다.
