#!/usr/bin/env python3

"""Precomputes CLIP embeddings for Simulacra Aesthetic Captions."""

import argparse
import os
import sqlite3
from pathlib import Path

import torch
import torchvision.transforms as transforms
from PIL import Image
from torch import multiprocessing as mp
from torch.utils import data
from tqdm import tqdm


class SimulacraDataset(data.Dataset):
    """Simulacra dataset
    Args:
        images_dir: directory
        transform: preprocessing and augmentation of the training images
    """

    def __init__(self, images_dir, db, transform=None):
        self.images_dir = Path(images_dir)
        self.transform = transform
        self.conn = sqlite3.connect(db)
        self.ratings = []
        for row in self.conn.execute(
            "SELECT generations.id, images.idx, paths.path, AVG(ratings.rating) FROM images JOIN generations ON images.gid=generations.id JOIN ratings ON images.id=ratings.iid JOIN paths ON images.id=paths.iid GROUP BY images.id"
        ):
            self.ratings.append(row)

    def __len__(self):
        return len(self.ratings)

    def __getitem__(self, key):
        gid, idx, filename, rating = self.ratings[key]
        image = Image.open(self.images_dir / filename).convert("RGB")
        if self.transform:
            image = self.transform(image)
        return image, torch.tensor(rating)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch-size", "-bs", type=int, default=10, help="the CLIP model")
    p.add_argument("--clip-model", type=str, default="ViT-B/16", help="the CLIP model")
    p.add_argument("--db", type=str, required=True, help="the database location")
    p.add_argument("--device", type=str, help="the device to use")
    p.add_argument(
        "--images-dir", type=str, required=True, help="the dataset images directory"
    )
    p.add_argument(
        "--num-workers", type=int, default=8, help="the number of data loader workers"
    )
    p.add_argument("--output", type=str, required=True, help="the output file")
    p.add_argument(
        "--start-method",
        type=str,
        default="spawn",
        choices=["fork", "forkserver", "spawn"],
        help="the multiprocessing start method",
    )
    args = p.parse_args()

    mp.set_start_method(args.start_method)
    device = torch.device("cpu")
    if args.device:
        device = torch.device(device)
    else:
        if torch.backends.cuda.is_built():
            device = torch.device("cuda")
        if torch.backends.mps.is_built():
            device = torch.device("mps")

    print("Using device:", device)

    clip_model, clip_tf = clip.load(args.clip_model, device=device, jit=False)
    clip_model = clip_model.eval().requires_grad_(False)

    dataset = SimulacraDataset(args.images_dir, args.db, transform=clip_tf)
    loader = data.DataLoader(dataset, args.batch_size, num_workers=args.num_workers)

    embeds, ratings = [], []

    for batch in tqdm(loader):
        images_batch, ratings_batch = batch
        embeds.append(clip_model.encode_image(images_batch.to(device)).cpu())
        ratings.append(ratings_batch.clone())

    obj = {
        "clip_model": args.clip_model,
        "embeds": torch.cat(embeds),
        "ratings": torch.cat(ratings),
    }

    torch.save(obj, args.output)


if __name__ == "__main__":
    main()
