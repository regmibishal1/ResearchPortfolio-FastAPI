import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
import numpy as np

logger = logging.getLogger(__name__)
router = APIRouter()

DISTRIBUTIONS = Literal["normal", "uniform", "exponential", "beta", "binomial", "poisson"]


class SampleRequest(BaseModel):
    distribution: DISTRIBUTIONS
    params: dict[str, float]
    n_samples: int = Field(default=1000, ge=100, le=10000)
    n_bins: int = Field(default=40, ge=5, le=100)


class HistogramBin(BaseModel):
    bin_start: float
    bin_end: float
    count: int
    frequency: float  # proportion 0-1


class SampleResponse(BaseModel):
    histogram: list[HistogramBin]
    stats: dict[str, float]
    distribution: str
    params: dict[str, float]
    n_samples: int


def _generate(distribution: str, params: dict[str, float], n: int) -> np.ndarray:
    rng = np.random.default_rng()

    match distribution:
        case "normal":
            mu = params.get("mean", 0.0)
            sigma = params.get("std", 1.0)
            if sigma <= 0:
                raise HTTPException(400, "std must be > 0")
            return rng.normal(mu, sigma, n)

        case "uniform":
            low = params.get("low", 0.0)
            high = params.get("high", 1.0)
            if low >= high:
                raise HTTPException(400, "low must be < high")
            return rng.uniform(low, high, n)

        case "exponential":
            scale = params.get("scale", 1.0)
            if scale <= 0:
                raise HTTPException(400, "scale must be > 0")
            return rng.exponential(scale, n)

        case "beta":
            a = params.get("alpha", 2.0)
            b = params.get("beta", 5.0)
            if a <= 0 or b <= 0:
                raise HTTPException(400, "alpha and beta must be > 0")
            return rng.beta(a, b, n)

        case "binomial":
            trials = int(params.get("n", 10))
            p = params.get("p", 0.5)
            if trials < 1 or not (0 < p < 1):
                raise HTTPException(400, "n must be >= 1 and 0 < p < 1")
            return rng.binomial(trials, p, n).astype(float)

        case "poisson":
            lam = params.get("lambda", 3.0)
            if lam <= 0:
                raise HTTPException(400, "lambda must be > 0")
            return rng.poisson(lam, n).astype(float)

        case _:
            raise HTTPException(400, f"Unknown distribution: {distribution}")


@router.post("/sample", response_model=SampleResponse)
async def sample_distribution(request: SampleRequest):
    """
    Sample from a statistical distribution and return histogram bins + summary stats.
    Public endpoint — no authentication required.
    """
    logger.info(
        "sample_distribution distribution=%s n=%d bins=%d params=%s",
        request.distribution,
        request.n_samples,
        request.n_bins,
        request.params,
    )
    samples = _generate(request.distribution, request.params, request.n_samples)

    counts, edges = np.histogram(samples, bins=request.n_bins)
    total = counts.sum()

    histogram = [
        HistogramBin(
            bin_start=round(float(edges[i]), 6),
            bin_end=round(float(edges[i + 1]), 6),
            count=int(counts[i]),
            frequency=round(float(counts[i]) / total, 6) if total > 0 else 0.0,
        )
        for i in range(len(counts))
    ]

    summary = {
        "mean": round(float(np.mean(samples)), 4),
        "std": round(float(np.std(samples)), 4),
        "min": round(float(np.min(samples)), 4),
        "max": round(float(np.max(samples)), 4),
        "median": round(float(np.median(samples)), 4),
        "q25": round(float(np.percentile(samples, 25)), 4),
        "q75": round(float(np.percentile(samples, 75)), 4),
    }

    return SampleResponse(
        histogram=histogram,
        stats=summary,
        distribution=request.distribution,
        params=request.params,
        n_samples=request.n_samples,
    )
