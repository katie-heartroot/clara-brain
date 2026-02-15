FROM python:3.12-slim

WORKDIR /app

# Copy brain files
COPY CLARA-SOUL.md CONTEXT.md GOALS.md WINS.md NEXT.md MEMORY.md BOOTSTRAP.md README.md ./brain/
COPY knowledge.json ./brain/
COPY memory/ ./brain/memory/
COPY images-seed.json ./brain/images-seed.json

# Copy app
COPY app/ ./app/

# Create persistent directories
RUN mkdir -p /data/brain/sessions /data/brain/memory /data/brain/images/thumbs

# Entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 7778

CMD ["/app/entrypoint.sh"]
