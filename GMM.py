from typing import Iterator, List
from abc import ABC, abstractmethod

import numpy as np
from sklearn import metrics
from torchmetrics.clustering import AdjustedRandScore, NormalizedMutualInfoScore
from torchmetrics import Accuracy, F1Score

import torch
from enum import Enum
from torch.distributions import (
    Normal,
    Categorical,
    Independent,
    MultivariateNormal,
    MixtureSameFamily
)
from torch.distributions.utils import logits_to_probs
import torch
import numpy
from sklearn.datasets import make_spd_matrix

def purity_score(y_true, y_pred):
    # compute contingency matrix (also called confusion matrix)
    contingency_matrix = metrics.cluster.contingency_matrix(y_true, y_pred)
    # return purity
    return np.sum(np.amax(contingency_matrix, axis=0)) / np.sum(contingency_matrix)


def make_random_scale_trils(num_sigmas: int, num_dims: int) -> torch.Tensor:
    """
    Make random lower triangle scale matrix. Generated by taking the The lower
    triangle of a random covariance matrix

    :param num_sigmas: number of matrices to make
    :param num_dims: covariance matrix size
    :return: random lower triangular scale matrices
    """

    return torch.tensor(numpy.array([
        numpy.tril(make_random_cov_matrix(num_dims))
        for _ in range(num_sigmas)
    ]), dtype=torch.float32)


def make_random_cov_matrix(num_dims: int, observations_per_variable: int = 10) -> numpy.ndarray:
    """
    Make random covariance matrix using observation sampling

    :param num_dims: number of variables described by covariance matrix
    :param samples_per_variable: number of observations for each variable used
        to generated covariance matrix
    :return: random covariance matrix
    """
    if num_dims == 1:
        return numpy.array([[1.0]])

    observations = numpy.random.normal(0, 1, (num_dims, observations_per_variable))
    return numpy.corrcoef(observations)


def warp_probs(probs: torch.Tensor, target_value: float = 0.75) -> torch.Tensor:
    """
    Warps probability distribution such that, for a list of probabilities of
    length n, the value 1/n becomes `target_value`.

    Derivation:
    (1/n) ** a = t
    a * log(1/n) = log(t)
    a = log(t) / log(1/n)

    :param probs: tensor describing the probability of each event
    :param target_value: the value 1/n would be assigned after scaling
    :return: probs rescaled such that 1/len(probs) = 1/2
    """
    alpha = numpy.log(target_value) / numpy.log(1 / len(probs))
    return probs ** alpha


class MixtureFamily(Enum):
    FULL = "full"                          # fully expressive eigenvalues
    DIAGONAL = "diagonal"                  # eigenvalues align with data axes
    ISOTROPIC = "isotropic"                # same variance for all directions
    SHARED_ISOTROPIC = "shared_isotropic"  # same variance for all directions and components
    CONSTANT = "constant"                  # sigma is not learned


FAMILY_NAMES = [family.value for family in MixtureFamily]


def get_mixture_family_from_str(family_name: str):
    for family in MixtureFamily:
        if family.value == family_name:
            return family

    raise ValueError(
        f"Unknown mixture family `{family_name}`. "
        f"Please select from {FAMILY_NAMES}"
    )


class MixtureModel(ABC, torch.nn.Module):
    def __init__(
            self,
            num_components: int,
            num_dims: int,
            init_radius: float = 1.0,
            init_mus: List[List[float]] = None
    ):
        """
        Base model for mixture models

        :param num_components: Number of component distributions
        :param num_dims: Number of dimensions being modeled
        :param init_radius: L1 radius within which each component mean should
            be initialized, defaults to 1.0
        """
        super().__init__()
        self.num_components = num_components
        self.num_dims = num_dims
        self.init_radius = init_radius
        self.init_mus = init_mus

        self.logits = torch.nn.Parameter(torch.zeros(num_components, ))

    def mixture_parameters(self) -> Iterator[torch.nn.Parameter]:
        return iter([self.logits])

    def get_probs(self) -> torch.Tensor:
        return logits_to_probs(self.logits)

    @abstractmethod
    def forward(self, x: torch.Tensor, y:torch.Tensor):
        raise NotImplementedError()

    @abstractmethod
    def constrain_parameters(self):
        raise NotImplementedError()

    @abstractmethod
    def component_parameters(self) -> Iterator[torch.nn.Parameter]:
        raise NotImplementedError()

    @abstractmethod
    def get_covariance_matrix(self) -> torch.Tensor:
        raise NotImplementedError()


class GmmFull(MixtureModel):
    def __init__(
            self,
            num_components: int,
            num_dims: int,
            num_feat: int,
            init_radius: float = 1.0,
            init_mus: List[List[float]] = None
    ):
        super().__init__(num_components, num_dims, init_radius)

        init_mus = (
            torch.tensor(self.init_mus, dtype=torch.float32)
            if self.init_mus is not None
            else torch.rand(num_components, num_dims).uniform_(-init_radius, init_radius)
        )
        self.embed = torch.nn.Linear(num_feat, num_dims, bias=False)
        self.mus = torch.nn.Parameter(init_mus)

        # lower triangle representation of (symmetric) covariance matrix

        lower_triangular = torch.tril(torch.rand(num_dims, num_dims))

        # Step 2: Make it positive definite
        diagonal_matrix = torch.diag(torch.ones(num_dims))  # Identity matrix

        epsilon = 1e-6  # Small constant to ensure positive definiteness

        positive_definite_matrix = lower_triangular @ lower_triangular.t() + diagonal_matrix * epsilon
        sigmas = [positive_definite_matrix for i in range(self.num_components)]
        sigmas = torch.stack(sigmas)

        self.scale_tril = torch.nn.Parameter(sigmas)

    def forward(self, x: torch.Tensor):

        x = self.embed(x)
        mixture = Categorical(logits=self.logits)
        components = MultivariateNormal(self.mus, self.scale_tril)
        mixture_model = MixtureSameFamily(mixture, components)

        nll_loss = -1 * mixture_model.log_prob(x).mean()

        return nll_loss

    def constrain_parameters(self, epsilon: float = 1e-6):
        with torch.no_grad():
            for tril in self.scale_tril:
                # cholesky decomposition requires positive diagonal
                tril.diagonal().abs_()

                # diagonal cannot be too small (singularity collapse)
                tril.diagonal().clamp_min_(epsilon)

    def component_parameters(self) -> Iterator[torch.nn.Parameter]:
        return iter([self.mus, self.scale_tril])

    def get_covariance_matrix(self) -> torch.Tensor:
        return self.scale_tril @ self.scale_tril.mT


class GmmDiagonal(MixtureModel):
    """
    Implements diagonal gaussian mixture model

    :param num_components: number of components
    """

    def __init__(
            self,
            num_components: int,
            num_dims: int,
            num_feat: int,
            device,
            init_radius: float = 1.0,
            init_mus: List[List[float]] = None
    ):
        super().__init__(num_components, num_dims, init_radius)

        init_mus = (
            torch.tensor(self.init_mus, dtype=torch.float32)
            if self.init_mus is not None
            else torch.rand(num_components, num_dims).uniform_(-init_radius, init_radius)
        )
        self.embed = torch.nn.Linear(num_feat, num_dims, bias=False)
        self.mus = torch.nn.Parameter(init_mus)
        # represente covariance matrix as diagonals
        self.sigmas_diag = torch.nn.Parameter(torch.rand(num_components, num_dims))
        self.n_clusters = num_components
        self.device = device

    def forward(self, x: torch.Tensor, y: torch.Tensor):

        b, _, _ = x.shape
        x = self.embed(x)
        mixture = Categorical(logits=self.logits)
        components = Independent(Normal(self.mus, self.sigmas_diag), 1)
        mixture_model = MixtureSameFamily(mixture, components)

        prob = mixture_model.log_prob(x)

        assigned_labels = self.get_cluster_assign(x)
        nll_loss = -1 * prob.mean()

        y = y[:, 0, :].reshape(-1)

        adj_rand_index = AdjustedRandScore()(assigned_labels.to(torch.long), y.to(torch.long))
        nmi = NormalizedMutualInfoScore()(assigned_labels.to(torch.long), y.to(torch.long))
        f1 = F1Score(task='multiclass', num_classes=self.n_clusters).to(self.device)(assigned_labels.to(torch.long),
                                                                                     y.to(torch.long))
        p_score = purity_score(y.to(torch.long).detach().cpu().numpy(),
                               assigned_labels.to(torch.long).detach().cpu().numpy())

        return nll_loss, adj_rand_index, nmi, f1, p_score, x

    def get_cluster_assign(self, x):

        probs = []

        with torch.no_grad():
            for i in range(self.num_components):
                component = Independent(Normal(self.mus[i], self.sigmas_diag[i]), 1)
                prob = component.log_prob(x)
                probs.append(prob)
            log_probs = torch.stack(probs, dim=-1)
            cluster_assign = torch.argmax(log_probs, dim=-1)
            cluster_assign = torch.mode(cluster_assign, dim=-1).values
            return cluster_assign

    def constrain_parameters(self, epsilon: float = 1e-6):
        with torch.no_grad():
            for diag in self.sigmas_diag:
                # cholesky decomposition requires positive diagonal
                diag.abs_()

                # diagonal cannot be too small (singularity collapse)
                diag.clamp_min_(epsilon)

    def component_parameters(self) -> Iterator[torch.nn.Parameter]:
        return iter([self.mus, self.sigmas_diag])

    def get_covariance_matrix(self) -> torch.Tensor:
        return torch.diag_embed(self.sigmas_diag)


def get_model(
        mixture_family: MixtureFamily,
        num_components: int,
        num_dims: int,
        radius: float
) -> torch.nn.Module:
    if mixture_family == MixtureFamily.FULL:
        return GmmFull(num_components, num_dims, radius)

    if mixture_family == MixtureFamily.DIAGONAL:
        return GmmDiagonal(num_components, num_dims, radius)

    raise NotImplementedError(
        f"Mixture family {mixture_family.value} not implemented yet"
    )