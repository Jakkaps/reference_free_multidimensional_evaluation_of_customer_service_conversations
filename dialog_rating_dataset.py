import random

import torch
from torch_geometric.data import Data, InMemoryDataset


class DialogRatingDataset(InMemoryDataset):
    def __init__(
        self,
        root,
        dataset,
        transform=None,
        pre_transform=None,
        pre_filter=None,
        split="train",
    ):
        self.dataset = dataset
        super().__init__(root, transform, pre_transform, pre_filter)
        path = self.processed_paths[0] if split == "train" else self.processed_paths[1]
        self.load(path)

    @property
    def processed_file_names(self):
        return [f"{self.root}/processed_train.pt", f"{self.root}/processed_test.pt"]

    def process(self):
        nodes = torch.load(f"{self.root}/nodes.pt")
        edge_idxs = torch.load(f"{self.root}/edge_idxs.pt")
        edges = torch.load(f"{self.root}/edges.pt")
        labels = torch.load(f"{self.root}/labels.pt")

        label_mean = labels.mean(dim=0)
        label_std = labels.std(dim=0)

        labels = (labels - label_mean) / label_std

        data_list = [
            Data(
                x=nodes[i],
                edge_index=edge_idxs[i],
                edge_attr=edges[i],
                y=labels[i],
                num_nodes=len(nodes[i]),
            )
            for i in range(len(nodes))
        ]

        split_idx = int(0.8 * len(data_list))
        train_data, test_data = data_list[:split_idx], data_list[split_idx:]

        self.save(train_data, self.processed_paths[0])
        self.save(test_data, self.processed_paths[1])
