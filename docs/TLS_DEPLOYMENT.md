# VIGENT TLS(HTTPS) 배포 가이드 (파일럿)

> 목적: 파일럿에서 서버를 **네트워크에 노출**할 때 통신을 암호화한다. VIGENT 는 HTTP 로 동작하므로
> TLS 종단(HTTPS)은 **역프록시** 또는 **uvicorn 직접 TLS** 로 붙인다. 인증 토큰·영상 프레임이 평문으로
> 흐르지 않게 하는 것이 핵심(토큰 탈취·영상 도청 방지).

관련: 토큰 인증·Host 허용목록은 [보안 강화(item3)] — `VIGENT_API_TOKEN`·`VIGENT_REQUIRE_TOKEN`·
`VIGENT_ALLOWED_HOSTS`. TLS 는 그 위에 **전송 암호화**를 더한다.

---

## 권장 아키텍처 (파일럿 최소 구성)

```
[브라우저/카메라] --HTTPS(443)--> [역프록시: Caddy/nginx] --HTTP(127.0.0.1:8010)--> [VIGENT uvicorn]
```
- VIGENT 는 **루프백(127.0.0.1)에 바인딩** → 외부에서 직접 도달 불가. 역프록시만 TLS 종단.
- VIGENT 에는 `VIGENT_API_TOKEN` 설정(역프록시가 헤더 전달) + `VIGENT_ALLOWED_HOSTS`에 서비스 도메인 지정.

---

## 방법 1 — Caddy (자동 HTTPS, 권장)

Caddy 는 공인 도메인이면 Let's Encrypt 인증서를 **자동 발급·갱신**한다. 설정이 가장 단순하다.

`Caddyfile`:
```
vigent.example.com {
    reverse_proxy 127.0.0.1:8010
    # 큰 영상 프레임 업로드 허용
    request_body {
        max_size 20MB
    }
}
```
```bash
# VIGENT (루프백 바인딩 + 토큰 + 허용호스트)
VIGENT_HOST=127.0.0.1 VIGENT_API_TOKEN=<비밀> VIGENT_ALLOWED_HOSTS=vigent.example.com \
  /opt/anaconda3/bin/python3 -m uvicorn main:app --host 127.0.0.1 --port 8010 &
# Caddy
caddy run --config Caddyfile
```
- 공인 도메인·80/443 인바운드가 있어야 자동 인증서 발급. 내부망이면 아래 자체서명 참고.

## 방법 2 — nginx + 인증서

`/etc/nginx/conf.d/vigent.conf`:
```nginx
server {
    listen 443 ssl;
    server_name vigent.example.com;
    ssl_certificate     /etc/ssl/vigent/fullchain.pem;
    ssl_certificate_key /etc/ssl/vigent/privkey.pem;
    client_max_body_size 20m;                 # 영상 프레임 업로드
    location / {
        proxy_pass http://127.0.0.1:8010;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
- 공인 도메인: `certbot --nginx -d vigent.example.com` (Let's Encrypt).
- `Host $host` 전달 → VIGENT `VIGENT_ALLOWED_HOSTS=vigent.example.com` 와 일치해야 통과.

## 방법 3 — uvicorn 직접 TLS (프록시 없이 간단히)

```bash
VIGENT_HOST=0.0.0.0 VIGENT_API_TOKEN=<비밀> VIGENT_ALLOWED_HOSTS=<도메인 or IP> \
  /opt/anaconda3/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8443 \
  --ssl-keyfile /etc/ssl/vigent/privkey.pem --ssl-certfile /etc/ssl/vigent/fullchain.pem
```
- 외부 바인딩이므로 `VIGENT_API_TOKEN` 이 **필수**(미설정 시 기동 거부). 자동갱신은 별도(cron certbot).

---

## 인증서 발급

- **공인 도메인**: Let's Encrypt(Caddy 자동 / nginx+certbot) — 무료·자동갱신. 권장.
- **내부망(도메인 없음)**: 자체서명 인증서(브라우저 경고 수용 or 사설 CA 배포).
  ```bash
  openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
    -keyout privkey.pem -out fullchain.pem -subj "/CN=vigent-internal"
  ```

## 파일럿 보안 체크리스트

- [ ] VIGENT 는 `127.0.0.1` 바인딩(역프록시 사용 시) 또는 외부바인딩+TLS+토큰.
- [ ] `VIGENT_API_TOKEN` 설정(강제하려면 `VIGENT_REQUIRE_TOKEN=1`).
- [ ] `VIGENT_ALLOWED_HOSTS` 에 실제 서비스 도메인/IP 지정(DNS-rebinding 방어).
- [ ] HTTPS 로만 접속(HTTP→HTTPS 리다이렉트). 토큰이 평문으로 흐르지 않는지 확인.
- [ ] 인증서 자동갱신 동작 확인(certbot/Caddy).
- [ ] 방화벽: 443 만 인바운드, 8010 은 로컬만.
- [ ] (영상 개인정보) [PRIVACY_POLICY_DRAFT.md](PRIVACY_POLICY_DRAFT.md) 의 보관·접근통제 항목 확인.

> 주의(규칙7): 위 설정 예시는 **가이드**다. 실제 도메인·인증서·방화벽은 배포 환경에서 검증해야 하며,
> 이 문서 작성 시점에 특정 배포로 실증하지는 않았다.
