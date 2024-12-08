from torch import nn
import lightning as L

from .clarc import CLARC
from .hooks import add_clarc_hook


class PCLARC(CLARC):
    def __init__(self, model: L.LightningModule, experiment_name: str, device: str):
        super().__init__(model, experiment_name, device)

    def apply_model_correction(self, cav_layer: str, alpha: float = 1.0) -> None:
        hook = add_clarc_hook(
            self.model, self.cav, self.mean_act_na, [cav_layer], alpha
        )
        self.hooks.append(hook)
