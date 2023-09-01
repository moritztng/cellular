import torch
import torch.nn.functional as torch_functions

class GameOfLife:
    def __init__(self, device):
        self.parameters = torch.zeros((2, 2, 3, 3), dtype=torch.float32, device=device)
        self.parameters[1, 1, :, :] = 1
        self.parameters[1, 1, 1, 1] = 9
   
    def __call__(self, state):
        next_state = torch_functions.pad(state, (1, 1, 1, 1), mode="circular")
        next_state = torch_functions.conv2d(next_state, self.parameters)
        next_state = ((next_state == 3) + (next_state == 11) + (next_state == 12)).to(torch.float32)
        next_state[:, 0, :, :] = 1 - next_state[:, 1, :, :]
        return next_state

class FallingSand:
    def __init__(self, device):
        self.parameters = torch.zeros((3, 3, 3, 3), dtype=torch.float32, device=device)
        self.parameters[1, 1, 1, 1] = 4
        self.parameters[1, 1, 2, 0] = 1
        self.parameters[1, 1, 2, 1] = 1
        self.parameters[1, 1, 2, 2] = 1
        self.parameters[1, 2, 1, 1] = 1
        self.parameters[2, 2, 0, 1] = 4
        self.parameters[2, 2, 0, 0] = 3
        self.parameters[2, 1, 1, 0] = 1
        self.parameters[2, 2, 0, 2] = 3
        self.parameters[2, 1, 1, 2] = 1
        self.parameters[2, 1, 1, 1] = -12
    
    def __call__(self, state):
        next_state = torch_functions.pad(state, (1, 1, 1, 1), mode="circular")
        next_state = torch_functions.conv2d(next_state, self.parameters)
        next_state = (next_state > 3).to(torch.float32)
        next_state[:,0,:,:] = 1 - next_state.sum(1)
        return next_state

class Growth:
    def __init__(self, device):
        self.parameters = torch.zeros((3, 3, 3, 3), dtype=torch.float32, device=device)
        self.parameters[1, 1, 1, 1] = 9
        self.parameters[2, 2, :, :] = 1
        self.parameters[2, 2, 1, 1] = 9
        self.parameters[2, 1, 1, 1] = 8

    def __call__(self, state):
        next_state = torch_functions.pad(state, (1, 1, 1, 1), mode="circular")
        next_state = torch_functions.conv2d(next_state, self.parameters)
        next_state = (next_state > 8).to(torch.float32)
        next_state[:, 1, :, :] *= 1 - next_state[:, 2, :, :]
        next_state[:, 0, :, :] = 1 - next_state.sum(1)
        return next_state
