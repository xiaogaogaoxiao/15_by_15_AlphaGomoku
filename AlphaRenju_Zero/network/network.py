from keras.engine.topology import Input
from keras.engine.training import Model
from keras.layers import add
from keras.layers.convolutional import Conv2D
from keras.layers.core import Activation, Dense, Flatten
from keras.layers.normalization import BatchNormalization
from keras.regularizers import l2
from keras.optimizers import SGD
from ..rules import *
import numpy as np


class Network():
    def __init__(self, conf):
        # Some Hyperparameters
        self._board_size = conf['board_size'] # the size of the playing board
        self._lr = conf['learning_rate'] # learning rate of SGD (2e-3)
        self._momentum = conf['momentum'] # nesterov momentum (1e-1)
        self._l2_coef = conf['l2'] # coefficient of L2 penalty (1e-4)
        # Define Network
        self._build_network()
        # File Location
        self._net_para_file = conf['net_para_file'] 
        # If we use previous model or not
        self._use_previous_model = conf['use_previous_model']
        if self._use_previous_model:            
            net_para = self._model.load_weights(self._net_para_file)
            self._model.set_weights(net_para)
            
    def _build_network(self):
        # Input_Layer
        init_x = Input((3, self._board_size, self._board_size))
        x = init_x
        # Convolutional Layer
        x = Conv2D( filters=32, kernel_size=(3, 3), strides=(1, 1), padding='same', data_format='channels_first', kernel_regularizer=l2(self._l2_coef))(x)
        x = BatchNormalization()(x)
        x = Activation('relu')(x)
        # Residual Layer
        x = self._residual_block(x)
        x = self._residual_block(x)
        x = self._residual_block(x)
        # Policy Head 
        policy = Conv2D(filters=2, kernel_size=(1, 1), strides=(1, 1), padding='same', data_format='channels_first', kernel_regularizer=l2(self._l2_coef))(x)
        policy = BatchNormalization()(policy)
        policy = Activation('relu')(policy)
        policy = Flatten()(policy)
        policy = Dense(self._board_size*self._board_size, kernel_regularizer=l2(self._l2_coef))(policy)
        self._policy = Activation('softmax')(policy)
        # Value Head
        value = Conv2D(filters=1, kernel_size=(1, 1), strides=(1,1), padding='same', data_format="channels_first", kernel_regularizer=l2(self._l2_coef))(x)
        value = BatchNormalization()(value)
        value = Activation('relu')(value)
        value = Flatten()(value)
        value = Dense(32, kernel_regularizer=l2(self._l2_coef))(value)
        value = Activation('relu')(value)
        value = Dense(1, kernel_regularizer=l2(self._l2_coef))(value)
        self._value = Activation('tanh')(value)
        # Define Network
        self._model = Model(inputs = init_x, outputs = [self._policy, self._value])
        # Define the Loss Function
        opt = SGD( lr=self._lr, momentum=self._momentum, nesterov=True)
        losses_type = ['categorical_crossentropy', 'mean_squared_error']
        self._model.compile(optimizer=opt, loss=losses_type)

    def _residual_block(self,x):
        x_shortcut = x
        x = Conv2D( filters=32, kernel_size=(3, 3), strides=(1,1), padding='same', data_format="channels_first", kernel_regularizer=l2(self._l2_coef))(x) 
        x = BatchNormalization()(x) 
        x = Activation('relu')(x)
        x = Conv2D( filters=32, kernel_size=(3, 3), strides=(1,1), padding='same', data_format="channels_first", kernel_regularizer=l2(self._l2_coef))(x) 
        x = BatchNormalization()(x) 
        x = add([x, x_shortcut]) # Skip Connection
        x = Activation('relu')(x)
        return x
        
    def predict(self, board, color):
        tensor = board2tensor(board, color)
        policy, value_tensor = self._model.predict_on_batch(tensor)
        value = value_tensor[0][0]
        return policy, value

    def train(self, board_list, color_list, pi_list, z_list):
        # Data Augmentation through symmetric transformation
        board_aug = []
        color_aug = []
        pi_aug = []
        z_aug = []
        for i in range(len(board_list)):
            new_board, new_color, new_pi, new_z = symmetric_data_augmentation(board_list[i], color_list[i], pi_list[i], z_list[i])
            board_aug.extend(new_board)
            color_aug.extend(new_color)
            pi_aug.extend(new_pi)
            z_aug.extend(new_z)
        board_list.extend(board_aug)
        color_list.extend(color_aug)
        pi_list.extend(pi_aug)
        z_list.extend(z_aug)
        # Regularize Data
        board_list = np.array([board2tensor(board_list[i], color_list[i], reshape_flag=False) for i in range(len(board_list))])
        pi_list = np.array(pi_list)
        z_list = np.array(z_list)
        # Training
        self._model.fit(board_list, [pi_list, z_list], epochs=20, batch_size=len(color_list), verbose=1)
        # Calculate Loss Explicitly
        loss = self._model.evaluate(board_list, [pi_list, z_list], batch_size=len(board_list), verbose=0)
        loss = loss[0]
        return loss
        
    def get_para(self):
        net_para = self._model.get_weights() 
        return net_para

    def save_model(self):
        """ save model para to file """
        self._model.save_weights(self._net_para_file)

    def load_model(self):
        self._model.load_weights(self._net_para_file)

def board2tensor(board, color, reshape_flag = True):
    """Current-Stone Layer"""
    cur = np.array(np.array(board) == color, dtype = np.int)
    """Enemy-Stone Layer"""
    e = np.array(np.array(board) == -color, dtype = np.int)
    """Color Layer"""
    flag = (1 if color == BLACK else 0)
    c = flag * np.ones((board.shape[0], board.shape[1]))
    """Stack cur,e,c into tensor"""
    tensor = np.array([cur, e, c])
    if reshape_flag:
        tensor = tensor.reshape(1, tensor.shape[0], tensor.shape[1], tensor.shape[2])
    return tensor   


def symmetric_data_augmentation(board, color, pi, z):
    new_board = []
    new_color = [color]*7
    new_pi = []
    new_z = [z]*7
    for type in range(1,8):
        board_t = board_transform(board,type,flag=1)
        pi_t = input_encode(pi, type, board.shape[0])
        new_board.append(board_t)
        new_pi.append(pi_t)
    return new_board, new_color, new_pi, new_z


def input_encode(vec, num, size):
    mat = np.reshape(vec, (size,size)) #reshape vector into matrix
    mat = board_transform(mat, num, flag = 1)
    vec = np.reshape(mat, (1, size**2))
    return vec[0]

def output_decode(vec, num, size):
    mat = np.reshape(vec, (size,size)) #reshape vector into matrix
    inv_mat = board_transform(mat, num, flag = 2)
    vec = np.reshape(inv_mat, (1, size**2))
    return vec[0]

def board_transform(mat, num, flag = 0):

    def R0(mat):
        return mat

    def R1(mat):
        mat = np.rot90(mat, 1)
        return mat

    def R2(mat):
        mat = np.rot90(mat, 2)
        return mat

    def R3(mat):
        mat = np.rot90(mat, 3)
        return mat

    def S(mat):
        mat = R0(np.fliplr(mat))
        return mat

    def SR1(mat):
        mat = R1(np.fliplr(mat))
        return mat

    def SR2(mat):
        mat = R2(np.fliplr(mat))
        return mat

    def SR3(mat):
        mat = R3(np.fliplr(mat))
        return mat

    if flag == 0:
        num = int(np.random.randint(8, size=1))
        total_type = ['R0', 'R1', 'R2', 'R3', 'S', 'SR1', 'SR2', 'SR3']
        real_type = total_type[num]
        return eval(real_type)(mat),num
    elif flag == 1: # encode
        total_type = ['R0', 'R1', 'R2', 'R3', 'S', 'SR1', 'SR2', 'SR3']
        real_type = total_type[num]
        return eval(real_type)(mat)
    else: # decode
        inv_total_type = ['R0', 'R3', 'R2', 'R1', 'S', 'SR1', 'SR2', 'SR3']
        real_type = inv_total_type[num]
        return eval(real_type)(mat)