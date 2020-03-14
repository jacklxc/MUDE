import model
import os, argparse, sys, time
import numpy as np
import utils
import torch
import torch.nn as nn
import torch.optim as optim

def save(model, save_filename):
    with open(save_filename, "wb") as f:
        torch.save(model, f)
    print('Saved as %s' % save_filename)


def output_s(message, save_filename):
    print (message)
    with open(save_filename, 'a') as out:
        out.write(message + '\n')


def vectorize_data(filename, vocab, id2vocab):
    # words are considered in a document-level 
    words = open(filename).read().replace('\n', ' <eos> ').strip().split()
    dataset = np.ndarray((len(words),), dtype=np.int32)
    for i, word in enumerate(words):
        if word not in vocab:
            # put one hot vector: len(vocab) as a index
            vocab[word] = len(vocab) 
            id2vocab[vocab[word]] = word
            # present input data as a sequence of one-hot vector
        dataset[i] = vocab[word]
    return dataset, vocab, id2vocab

def make_input_data(noise_data, data, seq_len, alph, vocab): # training, dev, or test
    max_char_num = 20

    X_vec = np.zeros((int(len(noise_data)/seq_len), seq_len, max_char_num), dtype=np.int32)
    mask_vec = np.zeros((int(len(noise_data)/seq_len), seq_len, max_char_num, max_char_num), dtype=np.int32)
    Y_vec = np.zeros((int(len(data)/seq_len), seq_len, 1), dtype=np.int32)

    for m, mini_batch_tokens in enumerate(zip(*[iter(noise_data)]*seq_len)):
        mask_mini_batch = np.zeros((seq_len, max_char_num, max_char_num), dtype=np.int32)
        x_mini_batch = np.zeros((seq_len, max_char_num), dtype=np.int32)
        y_mini_batch = np.zeros((seq_len, 1), dtype=np.int32)
        for j, token in enumerate(mini_batch_tokens):
            bin_all, mask_all = utils.vec_char(token, alph, max_char_num)
            x_mini_batch[j] = bin_all
            for k in range(max_char_num):
                mask_mini_batch[j][k] = mask_all
            true_token = data[m*seq_len:(m+1)*seq_len][j]
            y_mini_batch[j] = vocab[true_token]

        X_vec[m] = x_mini_batch
        mask_vec[m] = mask_mini_batch
        Y_vec[m] = y_mini_batch

        percentage = int(m*100. / (len(data)/seq_len))
        sys.stdout.write("\r%d %%" % (percentage))
        sys.stdout.flush()
    print('\n', X_vec.shape, mask_vec.shape, Y_vec.shape)
    return torch.LongTensor(X_vec), torch.LongTensor(mask_vec), torch.LongTensor(Y_vec)

def train(epoch, X_train, mask_train, Y_train, batch_size, seq_len, ntokens, char_vocab_size, args):
    if epoch % args.betapoint == 0:
        args.beta /= 2
        print ('Decrease beta = {}'.format(args.beta))

    model.train()
    start_time = time.time()
    total_loss = 0
    if args.num in [2, 3]:
        total_seq_loss = 0
        total_pred_loss = 0
    for batch, i in enumerate(range(0, X_train.size(0) - 1, batch_size)):
        X, mask, Y = utils.get_batch(X_train, mask_train, Y_train, batch_size, i)
        X = X.to(device)
        mask = mask.to(device)
        Y = Y.to(device)
        optimizer.zero_grad()
        
        if args.num == 1:
            output, hidden = model(X, mask)
            loss = criterion(output.view(-1, ntokens), Y.view(-1))
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
                
        if args.num in [2, 3]:
            output, hidden, seq_output = model(X, mask) # seq_output = b, l, c-1, char_vocab_size
            loss_pred = criterion(output.view(-1, ntokens), Y.view(-1))

            seq_pred = seq_output.view(-1, char_vocab_size) 
            loss_seq = seq_criterion(seq_pred, X[:,:,1:].contiguous().view(-1))
            loss = loss_pred + args.beta*loss_seq
            loss.backward()
            optimizer.step()
            total_pred_loss += loss_pred.item()
            total_seq_loss += loss_seq.item()
            total_loss += loss.item()

    elapsed = time.time() - start_time
    if args.num == 1:
        s = ('| epoch {:3d} | ms/epoch {:5.2f} | '
            'loss {:5.3f}'.format(epoch, elapsed * 1000, total_loss))
        output_s(s, message_filename)

    if args.num in [2,3]:
        s = ('| epoch {:3d} | ms/epoch {:5.2f} | '
            'pred_loss {:5.3f} | {:5.3f} x seq_loss {:5.3f} | loss {:5.3f} '.format(epoch, elapsed * 1000, 
            total_pred_loss, args.beta, total_seq_loss, total_loss))
        output_s(s, message_filename)

    return total_loss / X_train.size(0)

  

def evaluate(X_valid, mask_valid, Y_valid, batch_size, seq_len, ntokens, args):
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for batch, i in enumerate(range(0, X_valid.size(0) - 1, batch_size)):
            X, mask, Y = utils.get_batch(X_valid, mask_valid, Y_valid, batch_size, i)
            if args.num == 1:
                output, hidden = model(X, mask)
            if args.num in [2,3]:
                output, hidden, seq_output = model(X, mask)
            output = output.view(-1, ntokens)
            _, predicted = torch.max(output.data, 1)
            Y = Y.view(-1)
            total += Y.size(0)
            correct += (predicted == Y).sum().item()
        return 100*correct/total
        # check output
def decode_word(X,  id2vocab):
    return ' '.join(id2vocab[x.item()] for x in X)

def check(X_valid, mask_valid, Y_valid, valid_noise_tokens, valid_tokens, id2vocab, ntokens, seq_len, args):
    """
    X_valid: seq_len, seq_len, d_input
    Y_valid: seq_len, seq_len, 1
    """
    n = 3
    srcs = list(zip(*[iter(valid_noise_tokens)]*seq_len))[:n]

    for j in range(n):
        src_j = " ".join(srcs[j])
        x_raw, mask_raw, y_raw = X_valid[np.array([j])], mask_valid[np.array([j])], Y_valid[np.array([j])] # "np.array" to make the dim 3
        ref_j = decode_word(y_raw.view(-1), id2vocab)
        if args.num == 1:
            output, hidden = model(x_raw, mask_raw)
        if args.num in [2, 3]:
            output, hidden, seq_output = model(x_raw, mask_raw)
        output = output.view(-1, ntokens)
        _, predicted = torch.max(output.data, 1)
        print (predicted)
        pred_j = decode_word(predicted, id2vocab)

        print('example #', str(j+1))        
        print('SRC: ', src_j)
        print('REF: ', ref_j)        
        print('PRD: ', pred_j)
    return

def remove_elements(array, element):
    to_return = []
    for foo in array:
        if foo != element:
            to_return.append(foo)
    return to_return

def check_performance(X_valid, mask_valid, Y_valid, valid_noise_tokens, valid_tokens, id2vocab, ntokens, seq_len, args):
    """
    X_valid: seq_len, seq_len, d_input
    Y_valid: seq_len, seq_len, 1
    """
    stop_token = '<eos>'
    srcs = list(zip(*[iter(valid_noise_tokens)]*seq_len))

    TP = 0
    FP = 0
    FN = 0
    TN = 0

    for j in range(len(srcs) - 1):
        src_j = " ".join(srcs[j])
        src_tokens = remove_elements(srcs[j],stop_token)
        x_raw, mask_raw, y_raw = X_valid[np.array([j])], mask_valid[np.array([j])], Y_valid[np.array([j])] # "np.array" to make the dim 3
        ref_j = decode_word(y_raw.view(-1), id2vocab)
        ref_tokens = remove_elements(ref_j.split(), stop_token)
        if args.num == 1:
            output, hidden = model(x_raw, mask_raw)
        if args.num in [2, 3]:
            output, hidden, seq_output = model(x_raw, mask_raw)
        output = output.view(-1, ntokens)
        _, predicted = torch.max(output.data, 1)
        pred_j = decode_word(predicted, id2vocab)
        pred_tokens = remove_elements(pred_j.split(), stop_token)

        for token, gold, pred in zip(src_tokens, ref_tokens, pred_tokens):
            if token!=pred:
                if pred==gold:
                    TP += 1
                else:
                    FP += 1

            else:
                if pred==gold:
                    TN += 1
                else:
                    FN += 1

    try:
        precision = TP / (TP+FP)
        print("Precision:",precision)

        recall = TP / (TP+FN)
        print("Recall:",recall)
        beta = 0.5

        print("Accuracy:", (TP + TN)/(TP+FP+FN+TN))
        print("F 0.5:", (1+beta**2) * (precision * recall) / (beta**2 * precision + recall) )
    except ZeroDivisionError:
        print("Division by zero")
    return

def repackage_hidden(h):
    if isinstance(h, torch.Tensor):
        return h.detach()
    else:
        return tuple(repackage_hidden(v) for v in h)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--epochs', '-e', default=300, type=int,
        help='number of epochs to learn')
    parser.add_argument('--d_hidden', '-d', default=650, type=int,
        help='number of units in hidden layers')
    parser.add_argument('--seq_len', '-b', type=int, default=20,
        help='learning minibatch size')
    parser.add_argument('--betapoint', '-c', type=int, default=10,
        help='betapoint for decrease beta')
    parser.add_argument('--seed', type=int, default=1111)
    parser.add_argument('--lr', type=float, default=0.0001)
    parser.add_argument('--batch_size', type=int, default=64)
    parser.add_argument('--d_emb', type=int, default=512)
    parser.add_argument('--n', type=int, default=2)
    parser.add_argument('--h', type=int, default=8)
    parser.add_argument('--num', type=int, default=3)
    parser.add_argument('--beta', type=float, default=1.0)



    global device
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    lr = args.lr


    base_path = os.path.dirname(os.path.realpath(__file__))
    text_data_dir = os.path.join(base_path,'./data/')
    data_dir = os.path.join(base_path,'data/')
    output_dir = os.path.join(base_path,'output/')


    ######################################################
    ###########      DATA PREPARE              ###########
    ######################################################

    train_file = 'debug_label.txt'
    val_file = 'debug_label.txt'
    test_file = 'debug_label.txt'

    vocab, id2vocab = {'<eos>':0}, {0:'<eos>'}
    _, vocab, id2vocab = vectorize_data(text_data_dir + train_file, vocab, id2vocab)
    train_noise_filename = text_data_dir + 'debug.txt'
    train_noise_tokens = open(train_noise_filename).read().replace('\n', ' <eos> ').strip().split()
    train_filename = text_data_dir + train_file
    train_tokens = open(train_filename).read().replace('\n', ' <eos> ').strip().split()

    _, vocab, id2vocab = vectorize_data(text_data_dir + val_file, vocab, id2vocab)
    valid_noise_filename = text_data_dir + 'debug.txt'
    valid_noise_tokens = open(valid_noise_filename).read().replace('\n', ' <eos> ').strip().split()
    valid_filename = text_data_dir + val_file
    valid_tokens = open(valid_filename).read().replace('\n', ' <eos> ').strip().split()


    _, vocab, id2vocab = vectorize_data(text_data_dir + test_file, vocab, id2vocab)
    test_noise_filename = text_data_dir + 'debug.txt'
    test_noise_tokens = open(test_noise_filename).read().replace('\n', ' <eos> ').strip().split()
    test_filename = text_data_dir + test_file
    test_tokens = open(test_filename).read().replace('\n', ' <eos> ').strip().split()


    alph = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,:;'*!?`$%&(){}[]-/\@_#" 
    seq_len = args.seq_len
    print ('Process train data')
    X_train, mask_train, Y_train = make_input_data(train_noise_tokens, train_tokens, seq_len, alph, vocab)
    print ('Process valid data')
    X_valid, mask_valid, Y_valid = make_input_data(valid_noise_tokens, valid_tokens, seq_len, alph, vocab)
    print ('Process test data')
    X_test, mask_test, Y_test = make_input_data(test_noise_tokens, test_tokens, seq_len, alph, vocab)
        

    #X_train, mask_train, Y_train = X_train.to(device), mask_train.to(device), Y_train.to(device)
    X_valid, mask_valid, Y_valid = X_valid.to(device), mask_valid.to(device), Y_valid.to(device)
    X_test, mask_test, Y_test = X_test.to(device), mask_test.to(device), Y_test.to(device)
    ######################################################
    ###########    MODEL AND TRAINING CONFIG   ###########
    ######################################################
    model_name = "beta_{}_emb_{}_h_{}_hidden_{}_n_{}_lr_{}_bs_{}_check_{}".format(args.beta, args.d_emb, 
                                                                        args.h, args.d_hidden, args.n, args.lr, args.batch_size, args.betapoint)
    global message_filename 
    message_filename = output_dir + 'r_' + model_name + '.txt'
    model_filename = output_dir + 'm_' + model_name + '.pt'
    with open(message_filename, 'w') as out:
        out.write('start\n')
    char_vocab_size = len(alph)+5
    global model

    if args.num==3:
        model = model.MUDE(char_vocab_size, d_emb=args.d_emb, h=args.h, n=args.n, d_hidden=args.d_hidden, 
            vocab_size=len(vocab), dropout=0.01)
        #model = nn.DataParallel(model)
        model.to(device)
        
    global criterion
    criterion = nn.NLLLoss() 
    global seq_criterion
    seq_criterion = nn.NLLLoss(ignore_index=char_vocab_size-1) 

    global optimizer
    optimizer = getattr(optim, 'RMSprop')(model.parameters(), lr=lr)

    ######################################################
    ###########       START TRAINING           ###########
    ######################################################
    print (args)
    print (message_filename)


    best_acc = 0
    for epoch in range(1, args.epochs+1):
        epoch_start_time = time.time()
        train(epoch, X_train, mask_train, Y_train, args.batch_size, args.seq_len, len(vocab), char_vocab_size, args)
        val_acc = evaluate(X_valid, mask_valid, Y_valid, args.batch_size, args.seq_len, len(vocab), args)
        test_acc = evaluate(X_test, mask_test, Y_test, args.batch_size, args.seq_len, len(vocab), args)
        message = ('-' * 89
                +  '\n| end of epoch {:3d} | time: {:5.2f}s | valid acc {:5.2f} | '.format(
                    epoch, (time.time() - epoch_start_time), val_acc)
                +  '\n| end of epoch {:3d} | time: {:5.2f}s | test  acc {:5.2f} |\n'.format(
                    epoch, (time.time() - epoch_start_time), test_acc) 
                + '-' * 89)
        output_s(message, message_filename)

        # Save the model if the validation loss is the best we've seen so far.
        if val_acc > best_acc:
            save(model, model_filename)
            best_acc = val_acc
        #check(X_valid, mask_valid, Y_valid, valid_noise_tokens, valid_tokens, id2vocab, len(vocab), args.seq_len, args)
        check_performance(X_valid, mask_valid, Y_valid, valid_noise_tokens, valid_tokens, id2vocab, len(vocab), args.seq_len, args)

    check_performance(X_test, mask_test, Y_test, test_noise_tokens, test_tokens, id2vocab, len(vocab), args.seq_len, args)

if __name__=='__main__':
    main()
