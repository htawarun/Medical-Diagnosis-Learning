from collections import Counter
import numpy as np
import torch
import torch.utils.data as data


class FlatData(data.Dataset):
    def __init__(self, data, word_2_idx, label_map):
        super(FlatData, self).__init__()
        for i, row in enumerate(data):
            hadm_id = row[0]
            text = [word_2_idx[word] for sent in row[1] for word in sent]
            label = [label_map[l] for l in row[2].split(' ')]
            label_onehot = np.zeros(len(label_map.keys()))
            for l in label:
                label_onehot[l] = 1
            if i == 0:
                print("Example encoded data...")
                print(hadm_id, text, label, label_onehot)
                print()
            data[i] = {}
            data[i]['text_index_sequence'] = text
            data[i]['label'] = label_onehot
            data[i]['id'] = hadm_id
        self.data = data

    def __getitem__(self, index):
        return (self.data[index]['text_index_sequence'], self.data[index]['label'])

    def __len__(self):
        return len(self.data)


def flat_batch_collate(batch):
    max_note_len = max([len(_[0]) for _ in batch])
    x = torch.zeros(len(batch), max_note_len)
    y = []
    for i, example in enumerate(batch):
        y.append(np.asarray(example[1]))
        for j, word in enumerate(example[0]):
            x[i, j] = float(word)
    y = np.stack(y)
    # print(batch[0][0][50:55])
    # print(x[0][50:55])
    # print(batch[0][1])
    # print(y[0])
    # print(batch[8][0][50:55])
    # print(x[8][50:55])
    # print(batch[8][1])
    # print(y[8])
    return (x.long(), torch.from_numpy(y))


def build_dictionary(train_data, PADDING):
    vocab = []
    for d in train_data:
        note = d[1]
        for sent in note:
            vocab.extend(sent)
    vocab = [_[0] for _ in list(Counter(vocab).most_common()) if _[0] is not 'UNK']
    vocab = [PADDING, 'UNK'] + vocab
    print("Size of vocabulary: {}".format(len(vocab)))
    print("Top 100 words...")
    print(vocab[:100])
    print()
    word_indices = dict(zip(vocab, range(len(vocab))))
    return (word_indices, vocab)


def build_label_map(labels):
    label_indices = dict(zip(labels, range(len(labels))))
    return label_indices