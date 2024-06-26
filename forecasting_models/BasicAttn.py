import numpy as np
import torch
import torch.nn as nn


class BasicAttn(nn.Module):

    def __init__(self, d_k, device):

        super(BasicAttn, self).__init__()

        self.d_k = d_k
        self.device = device

    def forward(self, Q, K, V, mask=False):

        b, h, l, _ = Q.shape
        _, _, l_k, _ = K.shape

        scores = torch.einsum('bhqd,bhkd->bhqk', Q, K) / np.sqrt(self.d_k)

        if mask:

            mask = torch.tril(torch.ones(l, l_k)).to(torch.bool)
            mask = mask.unsqueeze(0).repeat(b, 1, 1).unsqueeze(1).repeat(1, h, 1, 1).to(self.device)
            scores.masked_fill_(mask, -1e10)

        attn = torch.softmax(scores, -1)
        context = torch.einsum('bhqk,bhvd->bhqd', attn, V)
        return context, attn