"""Development-only KMeans; subsequent snapshots use JSON frozen distances only."""
import math
import warnings
from itertools import combinations
from segmentation.contract import FEATURES, matrix, config, require, digest



def distances(x, model):
    import numpy as np
    require(model['status']=='available' and model['features']==list(FEATURES),'model','frozen model unavailable/columns changed')
    means=np.asarray(model['mean'],dtype=np.float64);scales=np.asarray(model['scale'],dtype=np.float64)
    centers=np.asarray(model['centers_standardized'],dtype=np.float64)
    require(means.shape==scales.shape==(4,) and centers.shape==(model['selected_k'],4)
            and np.isfinite(means).all() and np.isfinite(scales).all() and (scales>0).all()
            and np.isfinite(centers).all(),'model','invalid frozen numerical parameters')
    z=(x-means)/scales
    d=((z[:,None,:]-centers[None,:,:])**2).sum(axis=2)
    labels=d.argmin(axis=1) if len(x) else np.empty(0,dtype=int)
    ordered=np.sort(d,axis=1)
    return labels,d,ordered[:,1]-ordered[:,0] if len(x) else np.empty(0)






