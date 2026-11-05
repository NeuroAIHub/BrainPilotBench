# Deferred Airscope calcium-contact decoding

This proposal would predict four partner-contact states from a focal mouse's cortical calcium activity.
The author notebook derives those states from SAM2 masks using a minimum-distance threshold of 20 pixels.
The authors generated and plotted these sequences. Independent validation of the contact targets remains unresolved.
[Author notebook](https://github.com/Neurallabware/Airscope_toolbox/blob/80a01ecd8aafe7bb2eb2c0a74f76088c650fbf98/Data_release/experiments/multi_animal_interaction/visualize_data.ipynb)

The proposal is excluded from the runnable catalogue under the requirement for author-provided, validated evaluation labels.
Its local preparation, implementation and historical engineering checks are preserved in the maintainer archive.
The selected data and proposed split remain outside the published task collection.

The accepted [SAM2Mice tracking task](../../../tasks/animal-behavior/sam2mice-multi-animal-tracking/README.md) uses the author's benchmark bounding-box GT.
It predicts boxes and identities from original video frames.
