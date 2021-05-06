import tqdm
import pickle
import numpy as np
import os.path as p
from konlpy.tag import Mecab
from sklearn.feature_extraction.text import TfidfVectorizer

from retrieval.sparse import SparseRetrieval


class BM25Retrieval(SparseRetrieval):
    def __init__(self, args, b=0.01, k1=0.1):
        super().__init__(args)
        mecab = Mecab()
        self.b = b  # 0일 수록 문서 길이의 중요도가 낮아진다. 일반적으로 0.75 사용.
        self.k1 = k1  # TF의 saturation을 결정하는 요소. 어떤 토큰이 한 번 더 등장했을 때 이전에 비해 점수를 얼마나 높여주어야 하는가를 결정. (1.2~2.0을 사용하는 것이 일반적)
        self.encoder = TfidfVectorizer(tokenizer=mecab.morphs, ngram_range=(1, 2))

        self.avdl = None
        self.p_embedding = None

    def get_embedding(self):
        if p.isfile(self.embed_path) and p.isfile(self.encoder_path) and not self.args.retriever.retrain:
            with open(self.embed_path, "rb") as f:
                self.p_embedding = pickle.load(f)

            with open(self.encoder_path, "rb") as f:
                self.encoder = pickle.load(f)
        else:
            self.p_embedding, self.encoder = self._exec_embedding()

            with open(self.embed_path, "wb") as f:
                pickle.dump(self.p_embedding, f)

            with open(self.encoder_path, "wb") as f:
                pickle.dump(self.encoder, f)

        self.avdl = self.p_embedding.sum(1).mean()

    def _exec_embedding(self):
        self.encoder.fit(self.contexts)
        self.p_embedding = self.encoder.transform(self.contexts)
        return self.p_embedding, self.encoder

    def get_relevant_doc_bulk(self, queries, k=1):
        query_vecs = self.encoder.transform(queries)

        b, k1, avdl = self.b, self.k1, self.avdl
        len_p = self.p_embedding.sum(1).A1

        doc_scores = []
        doc_indices = []

        p_embedding = self.p_embedding.tocsc()

        for query_vec in tqdm.tqdm(query_vecs):
            p_emb_for_q = p_embedding.tocsc()[:, query_vec.indices]
            denom = p_emb_for_q + (k1 * (1 - b + b * len_p / avdl))[:, None]

            # idf(t) = log [ n / df(t) ] + 1 in sklearn, so it need to be converted
            # to idf(t) = log [ n / df(t) ] with minus 1
            idf = self.encoder._tfidf.idf_[None, query_vec.indices] - 1.0
            numer = p_emb_for_q.multiply(np.broadcast_to(idf, p_emb_for_q.shape)) * (k1 + 1)

            result = (numer / denom).sum(1).A1

            if not isinstance(result, np.ndarray):
                result = result.toarray()

            sorted_result_idx = np.argsort(result)[::-1]
            doc_score, doc_indice = result[sorted_result_idx].tolist()[:k], sorted_result_idx.tolist()[:k]
            doc_scores.append(doc_score)
            doc_indices.append(doc_indice)

        return doc_scores, doc_indices
