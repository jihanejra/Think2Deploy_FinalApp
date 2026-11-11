FROM apache/airflow:3.3.2-python3.12

# Bibliothèques du pipeline. "apache-airflow==<version>" est répété pour que pip ne
# mette pas à jour Airflow ou ses dépendances en installant BERTopic.
# PyTorch CPU : ~200 Mo au lieu de ~2,5 Go pour la version CUDA.
COPY requirements-pipeline.txt /tmp/requirements-pipeline.txt
RUN pip install --no-cache-dir --prefer-binary \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        "apache-airflow==${AIRFLOW_VERSION}" \
        -r /tmp/requirements-pipeline.txt

# Modèle d'embeddings téléchargé à la construction : pas de dépendance à Internet à 2h du matin
ENV HF_HOME=/opt/airflow/hf-cache USE_TF=0
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

# hdbscan 0.8.40 appelle check_array(force_all_finite=...), paramètre supprimé dans
# scikit-learn 1.8. Couche séparée pour réutiliser le cache des couches précédentes ;
# à intégrer à requirements-pipeline.txt lors d'une reconstruction complète.
RUN pip install --no-cache-dir "scikit-learn==1.7.2"
