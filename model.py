import torch
import torch.nn as nn
import torch.nn.functional as F
from peft import LoraConfig, TaskType, get_peft_model
from torch_geometric.loader import DataLoader
from torch_geometric.nn import MessagePassing
from transformers import AutoModel

from data import ChatDataset


class RelationAwareMP(MessagePassing):
    def __init__(self, n_relations, in_channels, out_channels):
        super().__init__(aggr="add")
        self.out_channels = out_channels
        self.n_relations = n_relations
        self.lins = nn.ModuleList(
            [nn.Linear(in_channels, out_channels) for _ in range(n_relations)]
        )
        self.norm_constants = nn.Parameter(torch.ones(n_relations))

    def forward(self, x, edge_index, edge_weights, edge_type):
        out = torch.zeros(x.size(0), self.out_channels, device=x.device)
        for relation_type in range(self.n_relations):
            mask = edge_type == relation_type
            relation_idxs = edge_index[:, mask]

            if relation_idxs.size(1) == 0:
                continue

            out += self.propagate(
                relation_idxs,
                x=x,
                edge_weights=edge_weights,
                type_idx=relation_type,
            )

        return F.relu(out)

    def message(self, x_j, edge_index_i, edge_index_j, edge_weights, type_idx):
        norm = (
            edge_weights[edge_index_i, edge_index_j] / self.norm_constants[type_idx]
        ).unsqueeze(-1)

        out = norm * self.lins[type_idx](x_j)
        return out


class MP(MessagePassing):
    def __init__(self, in_channels, out_channels):
        super(MP, self).__init__(aggr="add")
        self.lin = torch.nn.Linear(in_channels, out_channels)
        self.self_lin = torch.nn.Linear(in_channels, out_channels)

    def forward(self, x, edge_index):
        self_x = self.self_lin(x)
        return self.propagate(edge_index, x=x, self_x=self_x)

    def message(self, x_j):
        return self.lin(x_j)

    def update(self, aggr_out, self_x):
        return F.relu(aggr_out + self_x)


class UtteranceEmbedding(nn.Module):
    """Embeds dialog utterances into a fixed-size vector."""

    def __init__(self):
        super(UtteranceEmbedding, self).__init__()

        peft_config = LoraConfig(
            task_type=TaskType.FEATURE_EXTRACTION,
            inference_mode=False,
            r=8,
            lora_alpha=32,
            lora_dropout=0.1,
            target_modules=["query", "key", "value"],
        )
        model = AutoModel.from_pretrained(
            "sentence-transformers/paraphrase-MiniLM-L6-v2"
        )
        self.model = get_peft_model(model, peft_config)

    def forward(self, x):
        attn_mask = x.ne(0).int()
        out = self.model(x, attention_mask=attn_mask)
        embeddings = out.last_hidden_state[
            :, 0, :
        ]  # Index 0 for the [CLS] token in each sequence
        return embeddings


def pairwise_cosine_similarity(x, decay_factor=0.9):
    x_norm = x / x.norm(dim=1, keepdim=True)
    similarity_matrix = x_norm @ x_norm.T
    seq_length = x.size(0)
    for i in range(seq_length):
        for j in range(seq_length):
            distance = abs(j - i)
            similarity_matrix[i, j] *= decay_factor ** distance
    return similarity_matrix



class GraphEmbedding(nn.Module):
    def __init__(self, n_layers, n_relations, hidden_size, embed_size):
        super(GraphEmbedding, self).__init__()

        self.n_layers = n_layers

        self.embed = UtteranceEmbedding()
        self.relation_aware_mp = RelationAwareMP(
            n_relations=n_relations, in_channels=embed_size, out_channels=hidden_size
        )
        self.mp = MP(in_channels=hidden_size, out_channels=hidden_size)

    def forward(self, x, edge_index, edge_type, batch_size):
        # Embed utterances
        x = self.embed(x)

        # Construct edge weights
        edge_weights = pairwise_cosine_similarity(x)

        # Process the dialog graph
        for _ in range(self.n_layers):
            x = self.relation_aware_mp(x, edge_index, edge_weights, edge_type)
            x = self.mp(x, edge_index)

        # Aggregate to graph level
        x = x.view(batch_size, -1, x.size(-1))
        x = x.mean(dim=1)

        return x


class DialogDiscriminator(nn.Module):
    def __init__(
        self,
        n_graph_layers=1,
        n_graph_relations=9,
        hidden_size=384,
        embed_size=384,
    ):
        super(DialogDiscriminator, self).__init__()

        self.graph_embed = GraphEmbedding(
            n_layers=n_graph_layers,
            n_relations=n_graph_relations,
            hidden_size=hidden_size,
            embed_size=embed_size,
        )
        self.lin = nn.Linear(2 * hidden_size, 1)

    def forward(self, batch):
        x1, edge_index1, edge_type1 = batch.x1, batch.edge_index1, batch.edge_attr1
        x2, edge_index2, edge_type2 = batch.x2, batch.edge_index2, batch.edge_attr2

        batch_size = batch.num_graphs

        # Compute dialog embeddings
        x1 = self.graph_embed(x1, edge_index1, edge_type1, batch_size)
        x2 = self.graph_embed(x2, edge_index2, edge_type2, batch_size)

        # Concatenate dialog embeddings for both graphs
        x = torch.cat([x1, x2], dim=1)

        # Compute the final score from dialog embeddings
        return self.lin(x).squeeze()


if __name__ == "__main__":
    device = torch.device(
        "cuda"
        if torch.cuda.is_available()
        else ("mps" if torch.backends.mps.is_available() else "cpu")
    )

    eval_net = DialogDiscriminator()
    eval_net.to(device)

    chat_dataset = ChatDataset(root="data", dataset="twitter_cs")
    small_loader = DataLoader(chat_dataset, batch_size=2, shuffle=True)

    for batch in small_loader:
        batch = batch.to(device)
        try:
            out = eval_net(batch)
            print(out)
        except Exception as e:
            print(e)
        break

    batch = next(iter(small_loader))
    batch = batch.to(device)
    criterion = torch.nn.CrossEntropyLoss()
    # criterion = torch.nn.MSELoss()  # change when changed setup from continuous scores

    try:
        out = eval_net(batch)
        loss = criterion(out, batch.y)
        loss.backward()  # To check if gradients can be computed without error
        print(f"Loss calculated: {loss.item()}")
    except Exception as e:
        print(f"Error during training step: {e}")

    model = DialogDiscriminator().to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    # trainer = EvalNetTrainer(model, optimizer, criterion, device)

    # trainer.train(epochs=1, loader=loader)
    # trainer.eval(loader=loader)
    # trainer.save("trained_model.pth")
    # model = DialogDiscriminator()
    # model.to(device)

    # print_model_parameters(model)
    # print_model_parameters(model.graph_embed.embed.model)

    # chat_dataset = ChatDataset(root="data", dataset="twitter_cs")
    # loader = DataLoader(chat_dataset, batch_size=2, shuffle=True)
