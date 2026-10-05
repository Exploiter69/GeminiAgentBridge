FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt pyproject.toml README.md ./
RUN pip install --no-cache-dir -r requirements.txt
COPY gemini_web2api/ ./gemini_web2api/
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8081

# A production container must mount a real config containing the Gemini
# session material and an API key when binding beyond loopback.
CMD ["python", "-m", "gemini_web2api"]
