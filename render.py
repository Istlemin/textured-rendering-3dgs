#
# Copyright (C) 2023, Inria
# GRAPHDECO research group, https://team.inria.fr/graphdeco
# All rights reserved.
#
# This software is free for non-commercial, research and evaluation use 
# under the terms of the LICENSE.md file.
#
# For inquiries contact  george.drettakis@inria.fr
#

import torch
from depth_images import calibrate_depth
from scene import Scene
import os
from tqdm import tqdm
from os import makedirs
from gaussian_renderer import render
from textured_render import prerender_depth, textured_render_multicam
import torchvision
from utils.general_utils import safe_state
from argparse import ArgumentParser
from arguments import ModelParams, PipelineParams, get_combined_args
from gaussian_renderer import GaussianModel
import cv2
import numpy as np

def render_set(model_path, name, iteration, views,texture_views,gaussians, pipeline, background, render_type):
    render_path = os.path.join(model_path, name, "ours_{}".format(iteration), "renders")
    gts_path = os.path.join(model_path, name, "ours_{}".format(iteration), "gt")

    makedirs(render_path, exist_ok=True)
    makedirs(gts_path, exist_ok=True)

    for idx, view in enumerate(tqdm(views, desc="Rendering progress")):
        #import dill

        # view = dill.load(open("tmp/viewpoint_cam","rb"))
        # gaussians2 = dill.load(open("tmp/gaussians","rb"))
        # pipeline = dill.load(open("tmp/pipe","rb"))
        # background = dill.load(open("tmp/bg","rb"))
        
        #rendering_pkg = render(view, gaussians, pipeline, background)
        #texture_views = [views[i] for i in [15,21,26,37,42,43,40,69,53,58,72,74,82,98]]
        #texture_views = views[1:]

        if render_type == "texture":
            rendering_pkg = textured_render_multicam(view, texture_views,gaussians, pipeline, background,exclude_texture_idx=(idx if name=="train" else None))
            render_textured = cv2.inpaint(
                (rendering_pkg["render_textured"].cpu().numpy().transpose((1,2,0))*255).astype(np.uint8),
                (~rendering_pkg["render_textured_mask"].cpu().numpy()).transpose((1,2,0)).astype(np.uint8),
                10,
                cv2.INPAINT_TELEA
            )
            render_textured = torch.tensor(render_textured).permute((2,0,1)).float()/255
            torchvision.utils.save_image(render_textured, os.path.join(render_path, '{0:05d}'.format(idx) + "_texture.png"))
        else:
            rendering_pkg = render(view, gaussians, pipeline, background)

        rendering = rendering_pkg["render"]
        gt = view.original_image[0:3, :, :]
        torchvision.utils.save_image(rendering, os.path.join(render_path, '{0:05d}'.format(idx) + ".png"))
        torchvision.utils.save_image(rendering_pkg["render_depth"]*0.2, os.path.join(render_path, '{0:05d}'.format(idx) + "_depth.png"))
        torchvision.utils.save_image(rendering_pkg["render_opacity"], os.path.join(render_path, '{0:05d}'.format(idx) + "_opacity.png"))
        torchvision.utils.save_image(gt, os.path.join(gts_path, '{0:05d}'.format(idx) + ".png"))
        torchvision.utils.save_image(view.depth*0.2, os.path.join(gts_path, '{0:05d}'.format(idx) + "_depth.png"))

def render_sets(dataset : ModelParams, iteration : int, pipeline : PipelineParams, skip_train : bool, skip_test : bool, render_type):
    with torch.no_grad():
        gaussians = GaussianModel(dataset.sh_degree)
        scene = Scene(dataset, gaussians, load_iteration=iteration, shuffle=False)
        calibrate_depth(scene)

        print("Num gaussians:", len(gaussians.get_xyz))

        bg_color = [1,1,1] if dataset.white_background else [0, 0, 0]
        background = torch.tensor(bg_color, dtype=torch.float32, device="cuda")

        prerender_depth(scene.getTrainCameras(), gaussians, pipeline, background)

        if not skip_train:
             render_set(dataset.model_path, "train", scene.loaded_iter, scene.getTrainCameras(),scene.getTrainCameras(), gaussians, pipeline, background, render_type)

        if not skip_test:
             render_set(dataset.model_path, "test", scene.loaded_iter, scene.getTestCameras(),scene.getTrainCameras(), gaussians, pipeline, background, render_type)

if __name__ == "__main__":
    # Set up command line argument parser
    parser = ArgumentParser(description="Testing script parameters")
    model = ModelParams(parser, sentinel=True)
    pipeline = PipelineParams(parser)
    parser.add_argument("--iteration", default=-1, type=int)
    parser.add_argument("--skip_train", action="store_true")
    parser.add_argument("--skip_test", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--textured_render", action="store_true")
    args = get_combined_args(parser)
    print("Rendering " + args.model_path)

    render_type = "normal"
    if args.textured_render:
        render_type = "texture"

    # Initialize system state (RNG)
    safe_state(args.quiet)

    render_sets(model.extract(args), args.iteration, pipeline.extract(args), args.skip_train, args.skip_test, render_type)