# -*- coding: utf-8 -*-
"""circleyolov3_structure.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1iEFH7PO683lMetAo9gkXXWQkdmz4WMWF
"""
import torch
import torch.nn as nn
"""
Information about architecture config:
Tuple is structured by (filters, kernel_size, stride)
Every conv is a same convolution.
List is structured by "B" indicating a residual block followed by the number of repeats
"S" is for scale prediction block and computing the yolo loss
"U" is for upsampling the feature map and concatenating with a previous layer
"""
config = [
    (32, 3, 1),
    (64, 3, 2),
    ["B", 1],
    (128, 3, 2),
    ["B", 2],
    (256, 3, 2),
    ["B", 8],
    (512, 3, 2),
    ["B", 8],
    (1024, 3, 2),
    ["B", 4],  # To this point is Darknet-53
    (512, 1, 1),
    (1024, 3, 1),
    "S",
    (256, 1, 1),
    "U",
    (256, 1, 1),
    (512, 3, 1),
    "S",
    (128, 1, 1),
    "U",
    (128, 1, 1),
    (256, 3, 1),
    "S",
]

class Darknetconv2D_BN_Leaky(nn.Module): #DBL
    def __init__(self, input_channels, output_channels, batch_normal_act = True, **kwargs):
        super().__init__()
        self.batch_normal_act = batch_normal_act
        self.conv = nn.Conv2d(input_channels, output_channels, bias = not batch_normal_act,  **kwargs)
        self.BN = nn.BatchNorm2d(output_channels)
        self.leaky_relu = nn.LeakyReLU(0.1)

    def forward(self, x):
        if self.batch_normal_act:
            return self.leaky_relu(self.BN(self.conv(x)))
        else:
            return self.conv(x)

class Residual_block(nn.Module): #resn
    def __init__(self, channels, res_block = True, num_repeat = 1):
        super().__init__()
        self.layers = nn.ModuleList()
        self.res_block = res_block
        self.num_repeat = num_repeat

        #Res_unit
        for cnt in range(self.num_repeat):
            self.layers += [
                nn.Sequential(
                    Darknetconv2D_BN_Leaky(channels, channels // 2, kernel_size=1),
                    Darknetconv2D_BN_Leaky(channels // 2, channels, kernel_size=3, padding=1)
                )
            ]

    def forward(self, x):
        for layer in self.layers:
            x = layer(x) + x if self.res_block else layer(x)
        return x

class Feature_map(nn.Module):
    def __init__(self, in_channels, num_class, num_anchor_box):
        super().__init__()
        self.num_anchor_box = num_anchor_box
        self.num_class = num_class
        self.pred = nn.Sequential(
            Darknetconv2D_BN_Leaky(in_channels, 2*in_channels, kernel_size = 3, padding = 1), #DBL
            Darknetconv2D_BN_Leaky(2*in_channels, (self.num_class + 4) * self.num_anchor_box, batch_normal_act = False, kernel_size = 1) #conv              #1 num of anchor boxes
        )

    def forward(self, x):
        return (self.pred(x)
                .reshape(x.shape[0], self.num_anchor_box, self.num_class + 4, x.shape[2], x.shape[3]) #1 num of anchor boxes
                .permute(0, 1, 3, 4, 2)
                )
        # N x num_of_anchor_box x (H/32) x (W/32) x 4+num_class

class Yolo_V3(nn.Module):
    def __init__(self, num_class: int = 1, input_channels: int = 3, num_anchor_box: int = 1, **kwargs):
        super().__init__()
        self.num_class = num_class
        self.input_channels = input_channels
        self.num_anchor_box = num_anchor_box
        self.layers = self.__create_conv_layers()


    def forward(self, x):
      outputs = []
      route_connections = []

      for layer in self.layers:
          if isinstance(layer, Feature_map):
              outputs.append(layer(x))
              continue

          x = layer(x)

          if isinstance(layer, Residual_block) and layer.num_repeat == 8:
              route_connections.append(x)

          elif isinstance(layer, nn.Upsample):
              x = torch.cat([x, route_connections.pop()], dim=1)

      return outputs

    def __create_conv_layers(self):
        layers = nn.ModuleList()
        in_channels = self.input_channels

        for module in config:
            if isinstance(module, tuple):
                out_channels, kernel_size, stride = module
                layers.append(
                    Darknetconv2D_BN_Leaky(
                        in_channels,
                        out_channels,
                        kernel_size=kernel_size,
                        stride=stride,
                        padding = 1 if kernel_size == 3 else 0
                    )
                )
                in_channels = out_channels

            elif isinstance(module, list):
                num_repeat = module[1]
                layers.append(Residual_block(in_channels, num_repeat=num_repeat))

            elif isinstance(module, str):
                if module == "S":
                    layers += [
                        Residual_block(in_channels, res_block = False, num_repeat=1),
                        Darknetconv2D_BN_Leaky(in_channels, in_channels // 2, kernel_size=1),
                        Feature_map(in_channels // 2, num_class=self.num_class, num_anchor_box = self.num_anchor_box)
                    ]
                    in_channels = in_channels // 2

                elif module == "U":
                    layers.append(nn.Upsample(scale_factor=2))
                    in_channels = in_channels * 3 #concat after Upscaling

        return layers