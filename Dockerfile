FROM python:3.8
COPY .  /app
WORKDIR /app
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y libcgi-session-perl libhunspell-dev default-jre && rm -rf /var/lib/apt/lists/*
RUN pip install -r requirements.txt
RUN python -m spacy download en
EXPOSE 5000
# CMD ["python", "games.py"]
CMD ["gunicorn", "games:app", "--bind", "0.0.0.0:5000"]
