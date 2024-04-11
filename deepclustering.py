import numpy as np
import random
import torch.nn as nn
import torch
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import DotProduct, WhiteKernel
from modules.transformer import Transformer
from sklearn import metrics
from torchmetrics.clustering import AdjustedRandScore, NormalizedMutualInfoScore
from torchmetrics import Accuracy
from tslearn.metrics import SoftDTWLossPyTorch


torch.autograd.set_detect_anomaly(True)

torch.manual_seed(1234)
np.random.seed(1234)
random.seed(1234)


def purity_score(y_true, y_pred):
    # compute contingency matrix (also called confusion matrix)
    contingency_matrix = metrics.cluster.contingency_matrix(y_true, y_pred)
    # return purity
    return np.sum(np.amax(contingency_matrix, axis=0)) / np.sum(contingency_matrix)


class Autoencoder(nn.Module):
    def __init__(self, input_dim, encoding_dim):
        super(Autoencoder, self).__init__()
        self.encoder = nn.Sequential(
            nn.Linear(encoding_dim, 128),
            nn.ReLU(),
            nn.Linear(128, encoding_dim)
        )
        self.decoder = nn.Sequential(
            nn.Linear(encoding_dim, 128),
            nn.ReLU(),
            nn.Linear(128, input_dim),
        )

    def forward(self, x):
        x_encoded = self.encoder(x)
        x_decoded = self.decoder(x_encoded)
        return x_decoded


class DeepClustering(nn.Module):

    def __init__(self, input_size, knns,
                 d_model, nheads, n_clusters,
                 num_layers, attn_type, seed,
                 device, pred_len, batch_size,
                 var=1, gamma=0.1, gp=False):

        super(DeepClustering, self).__init__()

        self.device = device

        self.enc_embedding = nn.Linear(input_size, d_model)
        self.gp = gp
        self.gp_embedding = nn.Linear(input_size, d_model)

        self.seq_model = Transformer(input_size=d_model, d_model=d_model,
                                     nheads=nheads, num_layers=num_layers,
                                     attn_type=attn_type, seed=seed, device=device)

        self.proj_down = nn.Linear(d_model, input_size)

        self.pred_len = pred_len
        self.nheads = nheads
        self.batch_size = batch_size
        self.d_model = d_model
        self.input_size = input_size
        self.time_proj = 100
        self.num_clusters = n_clusters
        self.var = var
        self.k = knns
        self.gamma = gamma

    def forward(self, x, y=None):

        x_enc = self.enc_embedding(x)

        if self.gp:
           x_enc_1 = self.seq_model(x_enc)
           x_enc_gp = x_enc_1.reshape(-1, self.d_model)
           kernel = DotProduct() + WhiteKernel()
           x_enc_gp = x_enc_gp.detach().cpu().numpy()
           x_gp = x.detach().cpu().numpy().reshape(-1, self.input_size)
           gpr = GaussianProcessRegressor(kernel=kernel, random_state=0).fit(x_enc_gp, x_gp)
           preds = torch.from_numpy(gpr.predict(x_enc_gp)).to(self.device)
           preds = preds.to(x_enc_1.dtype)
           preds_gp = self.gp_embedding(preds).reshape(x_enc_1.shape)
           x_enc = self.seq_model(preds_gp)

        else:
            x_enc = self.seq_model(x_enc)

        s_l = x.shape[1]

        x_enc_re = x_enc.reshape(self.batch_size, -1)
        attn_score = torch.einsum('bl, cl-> bc', x_enc_re, x_enc_re) / np.sqrt(self.d_model * s_l)
        mask = torch.zeros_like(attn_score).fill_diagonal_(1).to(torch.bool)
        attn_score = attn_score.masked_fill(mask, value=-torch.inf)
        scores = torch.softmax(attn_score, dim=-1)

        x_rec = torch.einsum('bd, bc-> bd', x_enc_re, scores)
        x_rec = x_rec.reshape(x_enc.shape)
        x_rec_proj = self.proj_down(x_rec)

        # _, top_scores = torch.topk(scores, k=self.k, dim=-1)
        # x_rec_proj_exp = x_rec_proj.unsqueeze(0).expand(self.batch_size, -1, -1, -1)
        # x_rec_proj_exp_se = x_rec_proj_exp[torch.arange(self.batch_size)[:, None],
        #                                    top_scores]
        #
        # diff_1 = (torch.diff(x_rec_proj_exp_se, dim=1)**2).mean()
        # diff_2 = (torch.diff(x_rec_proj_exp_se, dim=2)**2).mean()

        if self.var == 1:
            loss = nn.MSELoss(reduction='none')
        else:
            loss = SoftDTWLossPyTorch(gamma=self.gamma)

        loss = loss(x_rec_proj, x).mean()

        #x_rec = self.proj_down(output_seq)

        # diffs = torch.diff(x_rec, dim=1)
        # kernel = 3
        # padding = (kernel - 1) // 2
        # mv_avg = nn.AvgPool1d(kernel_size=kernel, padding=padding, stride=1)(diffs.permute(0, 2, 1)).permute(0, 2, 1)
        # res = nn.MSELoss()(diffs, mv_avg)

        # dist_3d = torch.cdist(x_enc, self.centers, p=2)
        # _, cluster_ids = torch.min(dist_3d, dim=-1)
        #
        # assigned_centroids = self.centers[cluster_ids]
        #
        # distances = torch.norm(x_enc - assigned_centroids, dim=1)
        #
        # # Compute the mean squared distance
        # loss = torch.mean(distances ** 2)

        # mask = torch.zeros(self.batch_size, self.batch_size).to(self.device)
        # mask = mask.fill_diagonal_(1).to(torch.bool)
        # mask = mask.unsqueeze(-1).repeat(1, 1, s_l)
        # dist_3d = dist_3d.reshape(self.batch_size, self.batch_size, -1)
        #
        # dist_3d = dist_3d.masked_fill(mask, value=0.0)
        #
        # # x_rec = torch.einsum('lb, bd -> ld', dist_softmax, output_seq)
        # # x_rec_re = x_rec.reshape(self.batch_size, -1, self.d_model)
        # # x_rec_proj = self.proj_down(x_rec_re)
        # # loss_rec = nn.MSELoss()(x_rec_proj, x)
        #
        # knn_tensor, k_nearest = torch.topk(dist_3d, k=self.k, dim=1)


        # x_rec_expand = x_rec.unsqueeze(0).expand(self.batch_size, -1, -1)
        # k_nearest_e = k_nearest.unsqueeze(-1).repeat(1, 1, self.d_model)
        #
        # selected = x_rec_expand[torch.arange(self.batch_size)[:, None, None],
        #                         k_nearest_e,
        #                         torch.arange(self.d_model)[None, None, :]]
        #
        # selected = selected.reshape(self.batch_size, self.d_model, -1)
        #
        # diff_knns = (torch.diff(selected, dim=-1) ** 2).mean()
        # diff_steps = (torch.diff(selected, dim=1) ** 2).mean()

        #dist_knn = dist_softmax[torch.arange(self.batch_size)[:, None], k_nearest]

        #loss = loss_rec + diff_steps + diff_knns if self.var == 2 else loss_rec

        if y is not None:

            y = y[:, 0, :].reshape(-1)
            y_c = y.unsqueeze(0).expand(self.batch_size, -1)

            _, k_nearest = torch.topk(scores, k=self.k, dim=-1)
            labels = y_c[torch.arange(self.batch_size)[:, None],
                         k_nearest]

            assigned_labels = torch.mode(labels, dim=-1).values
            adj_rand_index = AdjustedRandScore()(assigned_labels.to(torch.long), y.to(torch.long))
            nmi = NormalizedMutualInfoScore()(assigned_labels.to(torch.long), y.to(torch.long))
            acc = Accuracy(task='multiclass', num_classes=self.num_clusters).to(self.device)(assigned_labels.to(torch.long), y.to(torch.long))
            p_score = purity_score(y.to(torch.long).detach().cpu().numpy(), assigned_labels.to(torch.long).detach().cpu().numpy())

        else:

            adj_rand_index = torch.tensor(0, device=self.device)
            nmi = torch.tensor(0, device=self.device)
            acc = torch.tensor(0, device=self.device)
            p_score = torch.tensor(0, device=self.device)

        return loss, adj_rand_index, nmi, acc, p_score, x_rec_proj
