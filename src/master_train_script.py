import csv
import re
import os
import random
from collections import Counter
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.data as data
from torch.autograd import Variable
import numpy as np
import math
import tensorboard_logger
import pickle
import time
import argparse
import subprocess

from attention_databuilder import *
from attention_models import *
#from preprocess_helpers import count_labels
from embedding_utils import *
from evaluate import *
from evaluate_multi import *
from loss import *
from sklearn.metrics import f1_score, precision_score, recall_score

parser = argparse.ArgumentParser(description='MIMIC III notes data preparation')
parser.add_argument('--exp_name', type=str, default='run')
parser.add_argument('--train_path', type=str, default='/misc/vlgscratch2/LecunGroup/laura/medical_notes/processed_data/10codesL5_UNK_content_2_top1_train_data.pkl')
parser.add_argument('--val_path', type=str, default='/misc/vlgscratch2/LecunGroup/laura/medical_notes/processed_data/10codesL5_UNK_content_2_top1_valid_data.pkl')
parser.add_argument('--model_dir', type=str, default='/misc/vlgscratch2/LecunGroup/laura/medical_notes/models/')
parser.add_argument('--attention', type=int, default=0)
parser.add_argument('--cbow', type=int, default=0)
parser.add_argument('--batch_size', type=int, default=16)
parser.add_argument('--num_workers', type=int, default=4)
parser.add_argument('--embed_dim', type=int, default=50)
parser.add_argument('--hidden_dim', type=int, default=100)
parser.add_argument('--focalloss', type=int, default=0)
parser.add_argument('--lr', type=float, default=1e-2)
parser.add_argument('--lr_decay_rate', type=float, default=0.9)
parser.add_argument('--lr_decay_epoch', type=int, default=10)
parser.add_argument('--num_epochs', type=int, default=10)
parser.add_argument('--log_interval', type=int, default=100)
parser.add_argument('--vocab_threshold', type=int, default=20)
parser.add_argument('--gpu_id', type=int, default=0)
parser.add_argument('--build_starspace', type=int, default=0)
parser.add_argument('--use_starspace', type=int, default=1)
parser.add_argument('--starspace_exec', type=str, default='./Starspace/run.sh')
parser.add_argument('--multilabel', type=int, default=0)
parser.add_argument('--embed_path', type=str, default="Starspace/stsp_model.tsv",
                    help='Where are the initialized embeddings?')
args = parser.parse_args()
print(args)


PADDING = "<PAD>"
UNKNOWN = "UNK"
_t = time.time()

torch.manual_seed(1)
use_cuda = torch.cuda.is_available()
if use_cuda:
    torch.cuda.set_device(args.gpu_id)
    #torch.backends.cudnn.enabled = False

# data reader
log_path = os.path.join('log', args.exp_name)
if not os.path.exists(log_path):
    os.makedirs(log_path)
else:
    exit("Log path already exists. Enter a new exp_name")

args.model_dir = os.path.join(args.model_dir, args.exp_name)
if not os.path.exists(args.model_dir):
    os.makedirs(args.model_dir)

tensorboard_logger.configure(log_path)


## MIMIC data code
traindata = pickle.load(open(args.train_path, 'rb'))
#count_labels(traindata, 50)
valdata = pickle.load(open(args.val_path, 'rb'))
#count_labels(valdata, 50)
print("Train size:", len(traindata))
print("Valid size:", len(valdata))
# traindata = chf_data(traindata)
# valdata = chf_data(valdata)
# print("CHF Train size:", len(traindata))
# print("CHF Valid size:", len(valdata))

if args.build_starspace:
    print("Building starspace embeddings. This will take a few minutes...")
    stsp_data = convert_unflat_data_to_starspace_format(traindata)
    write_starspace_format(stsp_data, "stsp_embeddings.txt")
    subprocess.call([args.starspace_exec])

label_map = {i:_ for _,i in enumerate(get_labels(traindata))}
print(label_map)
print(len(label_map))
vocabulary, token2idx  = build_vocab(traindata, PADDING, UNKNOWN, args.vocab_threshold)
print("Vocab size:", len(vocabulary))
print(vocabulary[:20])
print("====================== Data examples =======================")
for i in range(10):
    print(traindata[i])
    print("=============================================================")
print("=============================================================")
print(list(token2idx.keys())[:20])
print(label_map)
print(list(token2idx.values())[:20])
print("Label mix training data")
count_labels(traindata)
print("Label mix valid data")
count_labels(valdata)
num_labels = len(label_map)
print("Number of labels is {}".format(num_labels))
if args.use_starspace:
    # Load starspace embeddings into a dict
    #stsp_embed = load_starspace_embeds("Starspace/stsp_model.tsv", args.embed_dim)
    stsp_embed = load_starspace_embeds(args.embed_path, args.embed_dim)
    print(type(stsp_embed))
    print("Embeddings loaded")
    for i, k in enumerate(stsp_embed):
        print(k, stsp_embed[k])
        if i == 3:
            break
    # Create starspace embedding matrix
    emb_mat = create_starspace_embedding_matrix(stsp_embed,
                                                token2idx,
                                                len(vocabulary),
                                                args.embed_dim)
    print("Embedding matrix created")

one_hot = False
if args.multilabel:
    print("Labels are one hot")
    one_hot = True
trainset = NotesData(traindata, token2idx, UNKNOWN, label_map, one_hot)
valset = NotesData(valdata, token2idx, UNKNOWN, label_map, one_hot)
print("Data Loaded in %.2f mns."%((time.time()-_t)/60))

train_loader = torch.utils.data.DataLoader(dataset = trainset, batch_size=args.batch_size, shuffle=True,
                                                           num_workers=args.num_workers, collate_fn=sent_batch_collate)
val_loader = torch.utils.data.DataLoader(dataset = valset, batch_size=args.batch_size, shuffle=True,
                                                           num_workers=args.num_workers, collate_fn=sent_batch_collate)
print("data loader done")

if args.attention:
    print("Using hierachical attention model")
    #model = Ensemble(args.embed_dim, len(vocabulary), args.hidden_dim, args.batch_size, label_map)
    model = HANModel(args.embed_dim, len(vocabulary), args.hidden_dim, args.batch_size, label_map)
else:
    if args.cbow:
        print("Using CBOW model")
        model = CBOWSentModel(args.embed_dim, len(vocabulary), args.hidden_dim, args.batch_size, label_map)
    else:
        print("Using Hierachical model")
        model = WordSentModel(args.embed_dim, len(vocabulary), args.hidden_dim, args.batch_size, label_map)
print(model)

if args.use_starspace:
    # Init embeddings
    model.word_rnn.word_embed.weight.data.copy_(emb_mat)
    print("Model embeddings initialized with starspace")

# model.apply(xavier_weight_init)
if args.focalloss:
    print("Using focal loss")
    crit = FocalLoss(len(label_map), use_cuda)
else:
    if args.multilabel:
        print("Mutilabel, using BCE loss")
        crit = nn.BCEWithLogitsLoss()
    else:
        print("Using cross entropy loss")
        crit = nn.CrossEntropyLoss()
opti = torch.optim.Adam(model.parameters(), lr=args.lr, betas=(0.5, 0.999))
# opti = torch.optim.RMSprop(model.parameters(), lr=args.lr)

if use_cuda:
    model.cuda()
    if args.focalloss == 0:
      crit.cuda()
    if args.attention:
        model.wordattention.context = model.wordattention.context.cuda()
        model.sentattention.context = model.sentattention.context.cuda()

print("Starting training...")
step = 0
eg = True
#train_loss_mean = []
for n_e in range(args.num_epochs):
    train_correct = 0
    for batch in train_loader:
        if batch[0].size(0) != args.batch_size:
            continue
        if eg:
            print("Printing an example...")
            print(batch[0].size(), batch[1].size())
            eg = False
        # print("Num padded sentences: {}, Num padded words per sentence: {}".format(
            # batch[0].size(1), batch[0].size(2)))
        #num_labels = batch[0].size(2)
        word_hidden = model.word_rnn.init_hidden(batch[0].size(0) * batch[0].size(1))
        sent_hidden = model.sent_rnn.init_hidden()
        if use_cuda:
            word_hidden, sent_hidden = word_hidden.cuda(), sent_hidden.cuda()

        model.train()
        opti.zero_grad()
        batch_x = Variable(batch[0])
        batch_y = Variable(batch[1])
        length_x = batch[2].type(torch.FloatTensor).unsqueeze(1)
        length_x = Variable(length_x)

        if use_cuda:
            batch_x, batch_y = batch_x.cuda(), batch_y.cuda()
            length_x = length_x.cuda()

        pred_prob, w, s = model(batch_x, word_hidden, sent_hidden, length_x)
        loss = crit(pred_prob, batch_y)
        loss.backward()
        torch.nn.utils.clip_grad_norm(model.parameters(), 1.0)
        opti.step()

        step += 1
    if n_e % args.lr_decay_epoch == 0:
        args.lr *= args.lr_decay_rate
        print("LR changed to", args.lr)
        opti = torch.optim.Adam(model.parameters(), lr=args.lr, betas=(0.5, 0.999))

    # print(predicted[:20])
    # print(val_batch_y[:20])
    if args.multilabel:
        print("Evaluating on training set, multilabel eval")
        print("Number of labels is {}".format(num_labels))
        train_loss, train_acc, train_f1, train_precision, train_recall = eval_model_multi(model, train_loader, args.batch_size, crit, use_cuda, num_labels, args.batch_size)
        print("Evaluating on validation set, multilabel eval")
        val_loss, val_acc, val_f1, val_precision, val_recall = eval_model_multi(model, val_loader, args.batch_size, crit, use_cuda, num_labels, args.batch_size)
    else:
        print("Evaluating on training set")
        train_loss, train_acc, train_f1, train_precision, train_recall = eval_model(model, train_loader, args.batch_size, crit, use_cuda)
        print("Evaluating on validation set")
        val_loss, val_acc, val_f1, val_precision, val_recall = eval_model(model, val_loader, args.batch_size, crit, use_cuda)

    tensorboard_logger.log_value('train loss', train_loss, n_e)
    tensorboard_logger.log_value('train acc', train_acc, n_e)
    tensorboard_logger.log_value('val loss', val_loss, n_e)
    tensorboard_logger.log_value('val acc', val_acc, n_e)
    tensorboard_logger.log_value('val f1', val_f1, n_e)
    tensorboard_logger.log_value('val precision', val_precision, n_e)
    tensorboard_logger.log_value('val recall', val_recall, n_e)
 
    torch.save(model.state_dict(), os.path.join(args.model_dir, "%d.pth"%n_e))
    #break
