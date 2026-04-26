"""Cloud-training integrations.

Each provider lives in its own submodule (``modal_train.py``,
``runpod_train.py``, …). The Training Studio's UI calls into them
through a thin uniform API: ``check_setup() / submit_job() /
poll_job() / cancel_job() / download_artifact()``. Adding a new
provider means writing one module and one extra UI button — the
existing studio plumbing (recipe build, dataset export, registry
register) doesn't change.
"""
