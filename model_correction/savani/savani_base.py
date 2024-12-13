import numpy as np

import torch
import lightning as L
import torch.nn as nn
from torch.utils.data import DataLoader

from torch.nn.functional import softmax, sigmoid

from abc import ABC, abstractmethod

# Project imports
from ..model_correction import ModelCorrectionMethod
from .utils import phi_torch, phi_np


class SavaniBase(ModelCorrectionMethod, ABC):
    def __init__(
        self, model: nn.Module | L.LightningModule, experiment_name: str, device: str
    ) -> None:
        super().__init__(model, experiment_name, device)
        if isinstance(model, L.LightningModule):
            self.lightning_model = model

    @abstractmethod
    def apply_model_correction(self) -> None:
        raise NotImplementedError

    def objective_thresh(self, backend: str, cache_preds: bool = True) -> callable:
        if cache_preds:
            with torch.no_grad():
                # Assuming binary classification and logits
                y_raw_preds = self.model(self.X_torch)
                if self.options.get("outputs_are_logits", True):
                    y_probs = softmax(y_raw_preds, dim=1)
                else:
                    y_probs = y_raw_preds
                y_preds = y_probs[:, 1]
                y_preds_np = y_preds.detach().cpu().numpy()

        if backend == "torch":

            def objective(tau):
                phi, _ = self.phi_torch(tau, y_preds)
                return -phi.detach().cpu().numpy()
        elif backend == "np":

            def objective(tau):
                phi, _ = self.phi_np(tau, y_preds_np)
                return -phi
        else:
            raise ValueError(f"Backend {backend} not supported")

        return objective

    def phi_torch(self, tau, preds=None) -> tuple[torch.Tensor, torch.Tensor]:
        with torch.no_grad():
            if preds is None:
                # Assuming binary classification and logits
                y_raw_preds = self.model(self.X_torch)
                if self.options.get("outputs_are_logits", True):
                    y_probs = softmax(y_raw_preds, dim=1)
                else:
                    y_probs = y_raw_preds
                y_preds = y_probs[:, 1]
            else:
                y_preds = preds

            _tau = torch.tensor(tau, device=self.device)

            return phi_torch(
                self.Y_true_torch,
                y_preds > _tau,
                self.ProtAttr_torch,
                self.epsilon,
                self.bias_metric,
            )

    def phi_np(self, tau, preds=None) -> tuple[np.ndarray, np.ndarray]:
        with torch.no_grad():
            if preds is None:
                # Assuming binary classification and logits
                y_raw_preds = self.model(self.X_torch)
                if self.options.get("outputs_are_logits", True):
                    y_probs = softmax(y_raw_preds, dim=1)
                else:
                    y_probs = y_raw_preds
                y_preds_np = y_probs[:, 1].detach().cpu().numpy()
            else:
                y_preds_np = preds

            return phi_np(
                self.Y_true_np,
                y_preds_np > tau,
                self.ProtAttr_np,
                self.epsilon,
                self.bias_metric,
            )

    def get_corrected_model(self) -> L.LightningModule | nn.Module:
        if hasattr(self, "lightning_model"):
            return self.lightning_model
        else:
            return self.model

    def apply_hook(self, tau: float) -> None:
        def hook(module, input, output):
            # output = (output > tau).int() # doesn't allow gradients to flow
            # Assuming binary classification
            output[:, 1] = sigmoid((output[:, 1] - tau) * 10)  # soft thresholding
            output[:, 0] = 1 - output[:, 1]
            print(f"Hook applied, threshold: {tau}")
            return output

        hook_fn = hook

        # Register the hook on the model
        hooks = []
        for name, module in self.model.named_modules():
            if isinstance(module, nn.Linear) and name == self.last_layer_name:
                handle = module.register_forward_hook(hook_fn)
                print(f"Hook registered on layer: {name}")
                hooks.append(handle)

        self.hooks = hooks

    def check_layer_name_exists(self, layer_name: str) -> bool:
        for name, _ in self.model.named_modules():
            if name == layer_name:
                return True
        return False

    def unpack_batches(
        self, dataloader: DataLoader, frac: float
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        X, Y_true, ProtAttr = [], [], []
        all_batches = len(dataloader)
        n_batches = int(all_batches * frac)
        for i, batch in enumerate(dataloader):
            X.append(batch[0])
            Y_true.append(batch[1])
            ProtAttr.append(batch[2])
            if i == n_batches:
                break
        X = torch.cat(X)
        Y_true = torch.cat(Y_true)
        ProtAttr = torch.cat(ProtAttr)
        return X, Y_true, ProtAttr
