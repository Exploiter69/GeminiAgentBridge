FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY gemini_web2api/ ./gemini_web2api/
COPY pyproject.toml README.md ./

EXPOSE 8081

# A production container must mount a real config containing the Gemini
# cookie/session material and an API key when binding beyond loopback.
CMD ["python", "-m", "gemini_web2api"]
