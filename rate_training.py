import sys

import click
import torch
import torch.nn as nn
from torch.utils.data import Subset
from torch_geometric.loader import DataLoader

from dialog_discrimination_dataset import DialogDiscriminationDataset
from dialog_rating_dataset import DialogRatingDataset
from model.dialog_discriminator import DialogDiscriminator
from model.dialog_rater import DialogRater
from model_manager import MDCE, ModelManager, MultiDimensionMSELoss
from utils import get_file_names, get_torch_device, print_model_parameters


@click.command()
@click.option("--mode", default="train", help="Mode of operation")
@click.option("--lr", default=0.001, help="Learning rate")
@click.option("--epochs", default=1, help="Number of epochs")
@click.option("--batch_size", default=16, help="Batch size")
@click.option("--n_training_points", type=int, help="Number of training points")
@click.option("--n_layers", default=1, type=int, help="Number of layers")
@click.option("--graph_out_dim", default=10, type=int, help="Graph output dimension")
def main(
    mode: str,
    lr: float,
    epochs: int,
    batch_size: int,
    n_training_points: int,
    n_layers: int,
    graph_out_dim: int,
):
    # _, model_name = get_file_names(
    # lr, epochs, batch_size, n_training_points, n_layers, graph_out_dim
    # )
    model_name = "n_layers=10_graph_out_dim=10_epoch=6.pth"
    dataset = "ratings"
    root = f"data/{dataset}"
    model_path = f"ckpts/{model_name}"
    device = get_torch_device()

    state_dict = torch.load(model_path, map_location=device)
    graph_embed_state_dict = {
        k.replace("graph_embed.", ""): v
        for k, v in state_dict.items()
        if "graph_embed" in k
    }
    model = DialogRater(
        n_graph_layers=n_layers,
        graph_out_dim=graph_out_dim,
        n_hidden_layers=2,
        hidden_dim=128,
    )
    model.graph_embed.load_state_dict(graph_embed_state_dict)
    model.to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    manager = ModelManager(
        model, optimizer, criterion=MultiDimensionMSELoss(num_classes=4)
    )

    train_data = DialogRatingDataset(root=root, dataset=dataset)
    train_data = (
        Subset(train_data, range(n_training_points))
        if n_training_points
        else train_data
    )
    train_loader = DataLoader(train_data, batch_size=batch_size, shuffle=True)

    eval_data = DialogRatingDataset(root=root, dataset=dataset, split="test")
    eval_data = (
        Subset(eval_data, range(n_training_points)) if n_training_points else eval_data
    )
    eval_loader = DataLoader(eval_data, batch_size=batch_size)

    manager.train(
        epochs=epochs,
        train_loader=train_loader,
        eval_loader=eval_loader,
        batch_size=batch_size,
        num_classes=4,
    )


if __name__ == "__main__":
    main()
