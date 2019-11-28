from tensorflow.keras.layers import Lambda, Input, Dense, Layer, Flatten
from tensorflow.keras.models import Model
from tensorflow.keras.datasets import mnist
from tensorflow.keras.losses import mse, binary_crossentropy
from tensorflow.keras.utils import plot_model
from tensorflow.keras import backend as K
import tensorflow.keras as keras
import numpy as np
import time
import CNN


class VCE(CNN.CNN):
    def __init__(self, training_generator, conv_params, fcc_params, model_type="regression",
                 validation_generator=None, data_format="channels_last", use_multiprocessing=False, workers=1,
                 verbose=1, latent_dim=7, num_epochs=10, beta=1, model_name="my_model.h5", validation_freq=1,
                 plot_models=False, callbacks=None, metrics=None, save=False, lr=0.0001, num_gpu=1, train=True):

        super().__init__(training_generator, conv_params, fcc_params, model_type=model_type,
                         validation_generator=validation_generator, data_format=data_format,
                         callbacks=callbacks, metrics=metrics, num_epochs=num_epochs,
                         use_multiprocessing=use_multiprocessing, workers=workers, verbose=verbose, save=save,
                         model_name=model_name, num_gpu=num_gpu, lr=lr, validation_freq=validation_freq, train=False)

        self.beta = beta
        self.plot_models = plot_models
        self.latent_dim = latent_dim

        input_shape = self.input_shape
        input_data = Input(shape=(*input_shape, 1))

        self.encoder = self.encoder_model(input_shape, conv_params, latent_dim, input_encoder=input_data)
        self.decoder = self.decoder_model(fcc_params)

        output_vce = self.decoder(self.encoder(input_data)[2])
        vce = Model(input_data, output_vce, name='vce')
        vce.add_loss(self.vce_loss)
        vce = self.compile_vce_model(vce)

        print(vce.summary())
        if plot_models is True:
            plot_model(vce, to_file='my_vae.png', show_shapes=True)

        if train is True:
            t0 = time.time()
            history = vce.fit_generator(generator=self.training_generator, validation_data=self.validation_generator,
                                        use_multiprocessing=self.use_multiprocessing, workers=self.workers,
                                        verbose=self.verbose, epochs=self.num_epochs, shuffle=True,
                                        callbacks=self.callbacks, validation_freq=self.val_freq)
            t1 = time.time()
            print("This model took " + str((t1 - t0)/60) + " minutes to train.")
            self.history = history

        self.vce = vce

    def vce_loss(self, inputs, outputs, z_mu, log_z_variance):
        reconstruction_loss = len(outputs) * mse(inputs, outputs)
        kl_loss = -0.5 * K.sum(1 + log_z_variance - K.square(z_mu) - K.exp(log_z_variance), axis=-1)
        return K.mean(reconstruction_loss + self.beta * kl_loss)

    def compile_vce_model(self, vce_model):
        optimiser = keras.optimizers.Adam(lr=self.lr, beta_1=0.9, beta_2=0.999, epsilon=None, decay=0.0, amsgrad=True)
        vce_model.compile(optimizer=optimiser, metrics=self.metrics)
        return vce_model

    def encoder_model(self, input_shape_box, conv_params, latent_dim, input_encoder=None):
        if input_encoder is None:
            input_encoder = Input(shape=(self.input_shape,), name='encoder_input')

        z_mean, z_log_var, z = self.encoder_net(input_encoder, input_shape_box, conv_params, latent_dim)
        encoder = Model(input_encoder, [z_mean, z_log_var, z], name='encoder')

        print(encoder.summary())

        if self.plot_models is True:
            plot_model(encoder, to_file='my_encoder.png', show_shapes=True)
        return encoder

    def decoder_model(self, fcc_params):
        input_decoder = Input(shape=(self.latent_dim,), name='decoder_input')
        output_decoder = self.decoder_net(input_decoder, fcc_params)

        decoder = Model(input_decoder, output_decoder, name='decoder')
        print(decoder.summary())
        if self.plot_models is True:
            plot_model(decoder, to_file='my_decoder.png', show_shapes=True)
        return decoder

    def sampling(self, args):
        """
        Instead of sampling from Q(z|X), sample epsilon = N(0,I),
        then  z = z_mean + sqrt(var) * epsilon
        """
        z_mu, z_log_var = args

        batch = K.shape(z_mu)[0]
        dim = K.int_shape(z_mu)[1]

        epsilon = K.random_normal(shape=(batch, dim))
        return z_mu + K.exp(0.5 * z_log_var) * epsilon

    def encoder_net(self, inputs, input_shape_box, conv_params, latent_dim):
        # This is made of convolutional layers from CNN module
        initialiser = keras.initializers.he_uniform()

        x = self._conv_layers(inputs, input_shape_box, conv_params, initialiser)
        x = Flatten(data_format=self.data_format)(x)

        z_mean = Dense(latent_dim, name='z_mean')(x)
        z_log_var = Dense(latent_dim, name='z_log_var')(x)

        z = Lambda(self.sampling, output_shape=(latent_dim,), name='z')([z_mean, z_log_var])
        return z_mean, z_log_var, z

    def decoder_net(self, latent_inputs, fcc_params):
        # This is made of fully-connected layers from CNN module
        initialiser = keras.initializers.he_uniform()

        x = self._fcc_layers(latent_inputs, fcc_params, initialiser)
        outputs = Dense(1, activation='linear')(x)
        return outputs

    def predict_latent_mean_std(self, testing_data):
        encoder = self.encoder
        z_mean, z_var, z = encoder.predict(testing_data)
        return z_mean, np.exp(0.5 * z_var)

