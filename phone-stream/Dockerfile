# 배포용 이미지. TLS는 플랫폼/리버스프록시가 종단한다고 가정하고 HTTP로 뜬다.
# (iOS 카메라는 HTTPS 필수이므로, 배포 대상은 반드시 HTTPS를 제공해야 함 —
#  Fly.io/Render/Railway/Cloud Run 등 PaaS는 기본 제공)
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY static ./static

ENV PORT=8080
EXPOSE 8080
CMD ["python", "server.py"]
