import numpy as np
import torch
import torch.nn as nn
import random

from seed_manager import set_seed


class ConvAttn(nn.Module):

    def __init__(self, d_k, h, kernel, seed):

        super(ConvAttn, self).__init__()

        set_seed(seed)

        self.d_k = d_k
        self.conv_q = nn.Conv1d(in_channels=d_k*h, out_channels=d_k*h,
                                kernel_size=kernel,
                                padding=int(kernel/2), bias=False)
        self.conv_k = nn.Conv1d(in_channels=d_k * h, out_channels=d_k * h,
                                kernel_size=kernel,
                                padding=int(kernel / 2), bias=False)

    def forward(self, Q, K, V):

        b, h, l, d_k = Q.shape
        l_k = K.shape[2]

        Q = self.conv_q(Q.reshape(b, h*d_k, l))[:, :, :l].reshape(b, h, l, d_k)
        K = self.conv_k(K.reshape(b, h*d_k, l_k))[:, :, :l_k].reshape(b, h, l_k, d_k)

        scores = torch.einsum('bhqd,bhkd->bhqk', Q, K) / np.sqrt(self.d_k)
        attn = torch.softmax(scores, -1)
        context = torch.einsum('bhqk,bhvd->bhqd', attn, V)
        return context, attn