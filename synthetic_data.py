import math
import torch
import gpytorch
from torch.utils.data import TensorDataset, DataLoader, BatchSampler


class SyntheticDataLoader:

    def __init__(self, batch_size, max_samples):

        inputs, samples, labels = self.get_synthetic_samples()
        permuted_indices = torch.randperm(len(inputs))
        inputs = inputs[permuted_indices]
        samples = samples[permuted_indices]
        labels = labels[permuted_indices]

        input_hold_out = inputs[:batch_size]
        sample_hold_out = samples[:batch_size]
        labels_hold_out = labels[:batch_size]

        inputs = inputs[batch_size:]
        samples = samples[batch_size:]
        labels = labels[batch_size:]

        hold_out_tensor_data = TensorDataset(input_hold_out, sample_hold_out, labels_hold_out)

        self.hold_out_test = DataLoader(hold_out_tensor_data, batch_size=batch_size)

        self.list_of_test_loader = []
        self.list_of_train_loader = []

        max_samples = max_samples if max_samples != -1 else len(samples)

        train_data = TensorDataset(inputs[batch_size:], samples[batch_size:], labels[batch_size:])

        batch_sampler = BatchSampler(
            sampler=torch.utils.data.RandomSampler(train_data, num_samples=max_samples),
            batch_size=batch_size,
            drop_last=True,
        )

        self.list_of_train_loader.append(DataLoader(train_data, batch_sampler=batch_sampler))
        self.list_of_test_loader.append(DataLoader(TensorDataset(inputs[:batch_size],
                                                                 samples[:batch_size],
                                                                 labels[:batch_size]),
                                                                 batch_size=batch_size))
        self.n_folds = 1
        self.input_size = 1
        self.output_size = 1

    def get_synthetic_samples(self):

        # Training data is 100 points in [0,1] inclusive regularly spaced
        train_x = torch.linspace(0, 1, 100).view(1, -1, 1).repeat(4, 1, 1)
        # True functions are sin(2pi x), cos(2pi x), sin(pi x), cos(pi x)
        sin_y = torch.sin(train_x[0] * (2 * math.pi)) + 0.5 * torch.rand(1, 100, 1)
        sin_y_short = torch.sin(train_x[0] * math.pi) + 0.5 * torch.rand(1, 100, 1)
        cos_y = torch.cos(train_x[0] * (2 * math.pi)) + 0.5 * torch.rand(1, 100, 1)
        cos_y_short = torch.cos(train_x[0] * math.pi) + 0.5 * torch.rand(1, 100, 1)
        train_y = torch.cat((sin_y, sin_y_short, cos_y, cos_y_short)).squeeze(-1)

        # We will use the simplest form of GP model, exact inference

        class ExactGPModel(gpytorch.models.ExactGP):
            def __init__(self, train_x, train_y, likelihood):
                super(ExactGPModel, self).__init__(train_x, train_y, likelihood)
                self.mean_module = gpytorch.means.ConstantMean(batch_shape=torch.Size([4]))
                self.covar_module = gpytorch.kernels.ScaleKernel(
                    gpytorch.kernels.MaternKernel(batch_shape=torch.Size([4])),
                    batch_shape=torch.Size([4])
                )

            def forward(self, x):
                mean_x = self.mean_module(x)
                covar_x = self.covar_module(x)
                return gpytorch.distributions.MultivariateNormal(mean_x, covar_x)


        # initialize likelihood and model
        likelihood = gpytorch.likelihoods.GaussianLikelihood(batch_shape=torch.Size([4]))
        model = ExactGPModel(train_x, train_y, likelihood)

        model.train()
        likelihood.train()

        # Use the adam optimizer
        optimizer = torch.optim.Adam(model.parameters(), lr=0.1)  # Includes GaussianLikelihood parameters

        # "Loss" for GPs - the marginal log likelihood
        mll = gpytorch.mlls.ExactMarginalLogLikelihood(likelihood, model)
        training_iter = 100

        print("Fitting GP...")
        for i in range(training_iter):
            # Zero gradients from previous iteration
            optimizer.zero_grad()
            # Output from model
            output = model(train_x)
            # Calc loss and backprop gradients
            loss = -mll(output, train_y).sum()
            loss.backward()
            # print('Iter %d/%d - Loss: %.3f' % (i + 1, training_iter, loss.item()))
            optimizer.step()

        inputs = []
        samples = []
        labels = []

        with torch.no_grad():
            for i in range(1024):

                test_x = torch.linspace(0, 1, 100).view(1, -1, 1).repeat(4, 1, 1)
                observed_pred = likelihood(model(test_x))
                # Get mean
                mean = observed_pred.mean.detach().cpu()
                mean = mean.reshape(4, -1)
                label = torch.tensor([1, 2, 3, 4]).reshape(-1, 1)
                labels.append(label)
                samples.append(mean)
                inputs.append(test_x)

        labels = torch.cat(labels, dim=0)
        samples = torch.cat(samples, dim=0).unsqueeze(-1)
        inputs = torch.cat(inputs, dim=0)

        return inputs, samples, labels


