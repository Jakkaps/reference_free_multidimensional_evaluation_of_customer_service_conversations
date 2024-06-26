from statistics import mean

import torch
import torch.nn as nn
from torch import Tensor
from tqdm import tqdm

from utils import get_torch_device


class MultiDimensionMSELoss(nn.Module):
    def __init__(self, num_classes=None):
        super(MultiDimensionMSELoss, self).__init__()
        self.mse = nn.MSELoss(reduction="none")
        self.num_classes = num_classes

    def forward(self, output, target, n_dims=4):
        if target.dim() == 1 and self.num_classes:
            target = target.view((-1, self.num_classes))

        se = torch.abs(output[:, :n_dims] - target[:, :n_dims])
        mse = torch.mean(se, dim=0)
        dim_mse = torch.sum(mse)

        return dim_mse


class HingeLoss(nn.Module):
    def __init__(self):
        super(HingeLoss, self).__init__()

    def forward(self, output, target):
        hinge_loss = torch.clamp(1 - target * output, min=0)
        return torch.mean(hinge_loss)


class ModelManager(nn.Module):
    def __init__(
        self,
        model,
        optimizer,
        model_base_name="",
        criterion=HingeLoss(),
        device=get_torch_device(),
    ):
        super().__init__()
        self.model = model
        self.optimizer = optimizer
        self.criterion = criterion
        self.device = device
        self.model_base_path = model_base_name.split(".")[0]
        self.model_name = self.model_base_path.split("/")[-1]

    def save(self, path):
        torch.save(self.model.state_dict(), path)

    def load(self, path):
        self.model.load_state_dict(torch.load(path))

    def train(
        self,
        train_loader,
        eval_loader,
        epochs,
        loss_window=10,
        save_every_epoch=False,
        batch_size=None,
        num_classes=None,
        output_path="./output",
    ):
        self.model.train()

        for epoch in range(epochs):
            target, pred = [], []
            batch_losses = []
            progress_bar = tqdm(
                enumerate(train_loader),
                total=len(train_loader),
                desc=f"Epoch {epoch + 1}/{epochs}",
                leave=True,
            )

            for batch in train_loader:
                batch = batch.to(self.device)
                self.optimizer.zero_grad()

                out = self.model(batch)
                loss = self.criterion(out, batch.y)
                loss.backward()
                self.optimizer.step()

                target.extend(batch.y.cpu().detach().numpy())
                pred.extend(out.cpu().detach().numpy())

                batch_losses.append(loss.item())

                progress_bar.update(1)
                progress_bar.set_postfix(
                    epoch=mean(batch_losses),
                    window=mean(batch_losses[-loss_window:]),
                )

            progress_bar.close()

            if save_every_epoch:
                self.save(self.model_base_path + f"_epoch={epoch+1}.pth")

            eval_target, eval_preds = None, None
            if eval_loader:
                eval_target, eval_preds = self.eval(eval_loader)

            epoch_data = {
                "train_target": Tensor(target),
                "train_preds": Tensor(pred),
                "eval_target": eval_target,
                "eval_preds": eval_preds,
            }
            torch.save(
                epoch_data, f"{output_path}/{self.model_name}_epoch={epoch + 1}.pt"
            )

    def eval(self, loader, loss_window=10):
        self.model.eval()
        targets, preds = [], []

        batch_losses = []
        with torch.no_grad():
            progress_bar = tqdm(
                enumerate(loader), total=len(loader), desc="Evaluating", leave=True
            )
            for batch in loader:
                batch = batch.to(self.device)

                out = self.model(batch)
                loss = self.criterion(out, batch.y)

                targets.extend(batch.y.cpu().detach().numpy())
                preds.extend(out.cpu().detach().numpy())

                batch_losses.append(loss.item())
                progress_bar.set_postfix(
                    avg=mean(batch_losses),
                    window=mean(batch_losses[-loss_window:]),
                )
                progress_bar.update(1)

        return Tensor(targets), Tensor(preds)
