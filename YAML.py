
services:
  - type: web
    name: erp-motores
    runtime: python
    plan: starter
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn --workers 1 --bind 0.0.0.0:$PORT wsgi:app
    disk:
      name: erp-motores-dados
      mountPath: /var/data
      sizeGB: 1
    envVars:
      - key: PYTHON_VERSION
        value: 3.12.7
      - key: SECRET_KEY
        generateValue: true
      - key: DB_PATH
        value: /var/data/motores.db
      - key: UPLOAD_DIR
        value: /var/data/fotos
      - key: ERP_USER
        value: admin
      - key: ERP_PASSWORD_HASH
        sync: false
