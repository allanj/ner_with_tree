# 
# @author: Allan
#

import torch
import torch.nn as nn
import torch.nn.functional as F



class DepLabeledGCN(nn.Module):
    def __init__(self, config, input_dim):
        super().__init__()

        self.gcn_hidden_dim = config.dep_hidden_dim
        self.num_gcn_layers = config.num_gcn_layers
        self.gcn_mlp_layers = config.gcn_mlp_layers
        self.edge_gate = config.edge_gate
        # gcn layer
        self.layers = self.num_gcn_layers
        self.device = config.device
        self.mem_dim = self.gcn_hidden_dim
        # self.in_dim = config.hidden_dim + config.dep_emb_size  ## lstm hidden dim
        self.in_dim = input_dim  ## lstm hidden dim
        self.self_dep_label_id = torch.tensor(config.deplabel2idx[config.self_label]).long().to(self.device)

        print("[Model Info] GCN Input Size: {}, # GCN Layers: {}, #MLP: {}".format(self.in_dim, self.num_gcn_layers, config.gcn_mlp_layers))
        self.gcn_drop = nn.Dropout(config.gcn_dropout).to(self.device)

        # gcn layer
        self.W = nn.ModuleList()
        self.W_label = nn.ModuleList()

        if self.edge_gate:
            print("[Info] Labeled GCN model will be added edge-wise gating.")
            self.gates = nn.ModuleList()

        for layer in range(self.layers):
            input_dim = self.in_dim if layer == 0 else self.mem_dim
            self.W.append(nn.Linear(input_dim, self.mem_dim).to(self.device))
            self.W_label.append(nn.Linear(input_dim, self.mem_dim).to(self.device))
            if self.edge_gate:
                self.gates.append(nn.Linear(input_dim, self.mem_dim).to(self.device))

        self.w_params = nn.Parameter(torch.randn(len(config.deplabels), input_dim, self.mem_dim))

        self.dep_emb = nn.Embedding(len(config.deplabels), 1).to(config.device)

        # output mlp layers
        in_dim = config.hidden_dim
        layers = [nn.Linear(in_dim, self.gcn_hidden_dim).to(self.device), nn.ReLU().to(self.device)]
        for _ in range(self.gcn_mlp_layers - 1):
            layers += [nn.Linear(self.gcn_hidden_dim, self.gcn_hidden_dim).to(self.device), nn.ReLU().to(self.device)]

        self.out_mlp = nn.Sequential(*layers).to(self.device)



    def forward(self, gcn_inputs, word_seq_len, adj_matrix, dep_label_matrix):

        """

        :param gcn_inputs: batch_size x sent_len x input_size
        :param word_seq_len: batch_size x sent_len
        :param adj_matrix: batch_size x sent_len x sent_len  (0,1)
        :param dep_label_matrix: batch_size x sent_len x sent_len (with dependency label id)
        :return:
        """

        batch_size, sent_len, input_dim = gcn_inputs.size()

        denom = adj_matrix.sum(2).unsqueeze(2) + 1

        dep_embs = self.dep_emb(dep_label_matrix)  ## B x N x N x 1
        dep_embs = dep_embs.squeeze(3) * adj_matrix
        #
        self_val = self.dep_emb(self.self_dep_label_id)
        dep_denom = dep_embs.sum(2).unsqueeze(2) + self_val



        for l in range(self.layers):
            gcn_biinput = gcn_inputs.view(batch_size, 1, sent_len, input_dim).expand(batch_size, sent_len, sent_len, input_dim)  ## B x N x N x input_size
            adj_h_mat = gcn_biinput * adj_matrix.view(batch_size, sent_len, sent_len, 1)  ## B x N x N x input_size

            adj_w_mat = torch.gather(self.w_params, 0, dep_label_matrix.view(-1, 1, 1).expand(self.mem_dim, input_dim))
            # adj_w_mat = adj_w_mat.view(batch_size, sent_len, sent_len, self.mem_dim, input_dim)

            weighted_gcn_input = adj_w_mat.bmm(adj_h_mat.view(-1, input_dim, 1))
            weighted_gcn_input = weighted_gcn_input.view(batch_size, sent_len, sent_len, self.mem_dim).sum(2)  ## B x N x h
            weighted_gcn_input = weighted_gcn_input / denom
            gcn_inputs = F.relu(weighted_gcn_input)

            input_dim = self.mem_dim
            gcn_inputs = self.gcn_drop(gcn_inputs) if l < self.layers - 1 else gcn_inputs

        # for l in range(self.layers):
        #
        #     Ax = adj_matrix.bmm(gcn_inputs)  ## N x N  times N x h  = Nxh
        #     AxW = self.W[l](Ax)   ## N x m
        #     AxW = AxW + self.W[l](gcn_inputs)  ## self loop  N x h
        #     AxW = AxW / denom
        #
        #     Bx = dep_embs.bmm(gcn_inputs)
        #     BxW = self.W_label[l](Bx)
        #     BxW = BxW + self.W_label[l](gcn_inputs * self_val)
        #     BxW = BxW / dep_denom
        #
        #     if self.edge_gate:
        #         gx = adj_matrix.bmm(gcn_inputs)
        #         gxW = self.gates[l](gx)  ## N x m
        #         gate_val = torch.sigmoid(gxW + self.gates[l](gcn_inputs))  ## self loop  N x h
        #         gAxW = F.relu(gate_val * (AxW + BxW))
        #     else:
        #         gAxW = F.relu(AxW + BxW)
        #
        #     gcn_inputs = self.gcn_drop(gAxW) if l < self.layers - 1 else gAxW


        outputs = self.out_mlp(gcn_inputs)
        return outputs



