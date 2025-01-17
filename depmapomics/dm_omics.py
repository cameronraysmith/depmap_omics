from depmapomics import constants
from depmapomics import env_config
import os.path
import dalmatian as dm
import pandas as pd
import numpy as np

from genepy.utils import helper as h
from genepy import mutations as mut

from depmap_omics_upload import tracker as track
from depmapomics import expressions, mutations
from depmapomics import fusions as fusion
from depmapomics import copynumbers as cn


async def expressionPostProcessing(
    refworkspace=env_config.RNAWORKSPACE,
    samplesetname=constants.SAMPLESETNAME,
    colstoclean=["fastq1", "fastq2", "recalibrated_bam", "recalibrated_bam_index"],
    ensemblserver=constants.ENSEMBL_SERVER_V,
    doCleanup=True,
    samplesetToLoad="all",
    taiga_dataset=env_config.TAIGA_EXPRESSION,
    save_output=constants.WORKING_DIR,
    minsimi=constants.RNAMINSIMI,
    dropNonMatching=True,
    dataset_description=constants.RNAseqreadme,
    dry_run=False,
    samplesinset=[],
    rsemfilelocs=None,
    rnaqclocs={},
    starlogs={},
    compute_enrichment=False,
    **kwargs,
):
    """the full CCLE Expression post processing pipeline (used only by CCLE)
    @see postprocessing() to reproduce our analysis and for parameters
    Args:
        refworkspace (str): terra workspace where the ref data is stored
        sampleset (str, optional): sampleset where the red data is stored. Defaults to 'all'.
        save_output (str, optional): whether to save our data. Defaults to "".
        doCleanup (bool, optional): whether to clean the Terra workspaces from their unused output and lo. Defaults to True.
        colstoclean (list, optional): the columns to clean in the terra workspace. Defaults to [].
        ensemblserver (str, optional): ensembl server biomart version . Defaults to constants.ENSEMBL_SERVER_V.
        todrop (list, optional): if some samples have to be dropped whatever happens. Defaults to [].
        priority (list, optional): if some samples have to not be dropped when failing QC . Defaults to [].
        useCache (bool, optional): whether to cache the ensembl server data. Defaults to False.
        samplesetToLoad (str, optional): the sampleset to load in the terra workspace. Defaults to "all".
        geneLevelCols (list, optional): the columns that contain the gene level
        expression data in the workspace. Defaults to constants.RSEMFILENAME_GENE.
        trancriptLevelCols (list, optional): the columns that contain the transcript
        level expression data in the workspacce. Defaults to constants.RSEMFILENAME_TRANSCRIPTS.
        ssGSEAcol (str, optional): the rna file on which to compute ssGSEA. Defaults to "genes_tpm".
        renamingFunc (function, optional): the function to use to rename the sample columns
        (takes colnames and todrop as input, outputs a renaming dict). Defaults to None.
        compute_enrichment (bool, optional): do SSgSEA or not. Defaults to True.
        dropNonMatching (bool, optional): whether to drop the non matching genes
        between entrez and ensembl. Defaults to False.
        recompute_ssgsea (bool, optional): whether to recompute ssGSEA or not. Defaults to True.
        taiga_dataset (str, optional): the taiga dataset path to use for uploading results. Defaults to env_config.TAIGA_EXPRESSION.
        minsimi (float, optional): the minimum similarity to use for comparison to previous dataset. Defaults to 0.95.
        dataset_description (str, optional): the taiga dataset description to use. Defaults to constants.RNAseqreadme.
        tocompare (dict, optional): the columns to compare. Defaults to {"genes_expected_count": "CCLE_RNAseq_reads", "genes_tpm": "CCLE_expression_full", "proteincoding_genes_tpm": "CCLE_expression"}.
        rsemfilelocs (pd.DataFrame, optional): locations of RSEM output files if refworkspace is not provided (bypass interaction with terra)
        samplesinset (list[str], optional): list of samples in the sampleset if refworkspace is not provided (bypass interaction with terra)
        rnaqclocs (dict(str:list[str]), optional): dict(sample_id:list[QC_filepaths]) of rna qc file locations if refworkspace is not provided (bypass interaction with terra)
    """
    from taigapy import TaigaClient

    tc = TaigaClient()

    mytracker = track.SampleTracker()

    ccle_refsamples = mytracker.read_seq_table()

    folder = save_output + samplesetname + "/"

    if dry_run:
        folder = save_output + "dryrun/"

    h.createFoldersFor(folder)
    files, failed, _, renaming, lowqual, enrichments = await expressions.postProcess(
        refworkspace,
        samplesetname,
        save_output=folder,
        doCleanup=doCleanup,
        colstoclean=colstoclean,
        ensemblserver=ensemblserver,
        samplesetToLoad=samplesetToLoad,
        geneLevelCols=constants.RSEMFILENAME_GENE,
        trancriptLevelCols=constants.RSEMFILENAME_TRANSCRIPTS,
        ssGSEAcol="genes_tpm",
        dropNonMatching=dropNonMatching,
        dry_run=dry_run,
        samplesinset=samplesinset,
        rsemfilelocs=rsemfilelocs,
        rnaqclocs=rnaqclocs,
        compute_enrichment=compute_enrichment,
        **kwargs,
    )

    print("updating the tracker")

    track.updateTrackerRNA(
        failed,
        lowqual[lowqual.sum(1) > 3].index.tolist(),
        ccle_refsamples,
        samplesetname,
        refworkspace,
        samplesinset=samplesinset,
        starlogs=starlogs,
        dry_run=dry_run,
        newgs=None,
    )

    # subset and rename, include all PRs that have associated CDS-ids
    pr_table = mytracker.update_pr_from_seq(["rna"])

    renaming_dict = dict(list(zip(pr_table.MainSequencingID, pr_table.index)))
    h.dictToFile(renaming_dict, folder + "rna_seq2pr_renaming.json")
    pr_files = dict()
    for k, v in files.items():
        pr_files[k + "_profile"] = v[v.index.isin(set(renaming_dict.keys()))].rename(
            index=renaming_dict
        )
    if enrichments != None:
        enrichments = enrichments[
            enrichments.index.isin(set(renaming_dict.keys()))
        ].rename(index=renaming_dict)
        enrichments.to_csv(folder + "gene_sets_profile.csv")
    expressions.saveFiles(pr_files, folder)
    mytracker.close_gumbo_client()

    if not dry_run:
        print("uploading to taiga")
        tc.update_dataset(
            changes_description="new " + samplesetname + " release!",
            dataset_permaname=taiga_dataset,
            upload_files=[
                {
                    "path": folder + "transcripts_expected_count.csv",
                    "name": "transcripts_expectedCount_withReplicates",
                    "format": "NumericMatrixCSV",
                    "encoding": "utf-8",
                },
                {
                    "path": folder + "genes_expected_count.csv",
                    "name": "genes_expectedCount_withReplicates",
                    "format": "NumericMatrixCSV",
                    "encoding": "utf-8",
                },
                {
                    "path": folder + "proteincoding_genes_tpm_logp1.csv",
                    "name": "proteinCoding_genes_tpm_logp1_withReplicates",
                    "format": "NumericMatrixCSV",
                    "encoding": "utf-8",
                },
                {
                    "path": folder + "proteincoding_genes_tpm_profile_logp1.csv",
                    "name": "proteinCoding_genes_tpm_logp1_profile",
                    "format": "NumericMatrixCSV",
                    "encoding": "utf-8",
                },
                {
                    "path": folder + "transcripts_tpm_profile_logp1.csv",
                    "name": "transcripts_tpm_logp1_profile",
                    "format": "NumericMatrixCSV",
                    "encoding": "utf-8",
                },
                {
                    "path": folder + "genes_tpm_profile_logp1.csv",
                    "name": "genes_tpm_logp1_profile",
                    "format": "NumericMatrixCSV",
                    "encoding": "utf-8",
                },
                {
                    "path": folder + "transcripts_expected_count_profile.csv",
                    "name": "transcripts_expectedCount_profile",
                    "format": "NumericMatrixCSV",
                    "encoding": "utf-8",
                },
                {
                    "path": folder + "proteincoding_genes_expected_count_profile.csv",
                    "name": "proteinCoding_genes_expectedCount_profile",
                    "format": "NumericMatrixCSV",
                    "encoding": "utf-8",
                },
                {
                    "path": folder + "genes_expected_count_profile.csv",
                    "name": "genes_expectedCount_profile",
                    "format": "NumericMatrixCSV",
                    "encoding": "utf-8",
                },
            ],
            upload_async=False,
            dataset_description=dataset_description,
        )
        if enrichments != None:
            tc.update_dataset(
                changes_description="adding enrichments for new "
                + samplesetname
                + " release!",
                dataset_permaname=taiga_dataset,
                upload_files=[
                    {
                        "path": folder + "gene_sets_all.csv",
                        "name": "gene_set_enrichment_withReplicates",
                        "format": "NumericMatrixCSV",
                        "encoding": "utf-8",
                    },
                    {
                        "path": folder + "gene_sets_profile.csv",
                        "name": "gene_set_enrichment_profile",
                        "format": "NumericMatrixCSV",
                        "encoding": "utf-8",
                    },
                ],
                upload_async=False,
                dataset_description=dataset_description,
            )
        print("done")


async def fusionPostProcessing(
    refworkspace=env_config.RNAWORKSPACE,
    sampleset=constants.SAMPLESETNAME,
    fusionSamplecol=constants.SAMPLEID,
    taiga_dataset=env_config.TAIGA_FUSION,
    dataset_description=constants.FUSIONreadme,
    folder=constants.WORKING_DIR,
    **kwargs,
):
    """the full CCLE Fusion post processing pipeline (used only by CCLE)
    see postprocessing() to reproduce our analysis
    Args:
        refworkspace (str): terra workspace where the ref data is stored
        sampleset (str, optional): sampleset where the red data is stored. Defaults to 'all'.
        save_output (str, optional): whether and where to save our data. Defaults to "".
        todrop (list, optional): if some samples have to be dropped whatever happens. Defaults to [].
        samplesetToLoad (str, optional): the sampleset to load in the terra workspace. Defaults to "all".
        fusionSamplecol ([type], optional): [description]. Defaults to constants.SAMPLEID.
        taiga_dataset (str, optional): the taiga dataset path to use for uploading results. Defaults to env_config.TAIGA_EXPRESSION.
        dataset_description (str, optional): the taiga dataset description to use. Defaults to constants.RNAseqreadme.

    Returns:
        (pd.df): fusion dataframe
        (pd.df): filtered fusion dataframe
    """
    from taigapy import TaigaClient

    tc = TaigaClient()

    mytracker = track.SampleTracker()
    ccle_refsamples = mytracker.read_seq_table()

    previousQCfail = ccle_refsamples[ccle_refsamples.low_quality == 1].index.tolist()

    # TODO: include in rna_sample_renaming.json instead
    # lower priority versions of these lines were used

    folder = folder + sampleset + "/"

    fusions, fusions_filtered = fusion.postProcess(
        refworkspace,
        todrop=previousQCfail,
        save_output=folder,
        **kwargs,
    )

    # subset, rename from seqid to prid, and save pr-indexed matrices
    pr_table = mytracker.read_pr_table()
    renaming_dict = dict(list(zip(pr_table.MainSequencingID, pr_table.index)))
    fusions_pr = fusions[
        fusions[fusionSamplecol].isin(set(renaming_dict.keys()))
    ].replace({fusionSamplecol: renaming_dict})
    fusions_filtered_pr = fusions_filtered[
        fusions_filtered[fusionSamplecol].isin(set(renaming_dict.keys()))
    ].replace({fusionSamplecol: renaming_dict})

    fusions_pr.to_csv(os.path.join(folder, "fusions_all_profile.csv"), index=False)
    fusions_filtered_pr.to_csv(
        os.path.join(folder, "filteredfusions_latest_profile.csv"), index=False
    )

    mytracker.close_gumbo_client()

    # taiga
    print("uploading to taiga")
    tc.update_dataset(
        dataset_permaname=taiga_dataset,
        changes_description="new " + sampleset + " release!",
        upload_files=[
            {
                "path": folder + "/fusions_all.csv",
                "name": "fusions_unfiltered_withReplicates",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "/filteredfusions_latest_profile.csv",
                "name": "fusions_filtered_profile",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "/fusions_all_profile.csv",
                "name": "fusions_unfiltered_profile",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
        ],
        dataset_description=dataset_description,
    )
    print("done")
    return fusions


def cnPostProcessing(
    wesrefworkspace=env_config.WESCNWORKSPACE,
    wgsrefworkspace=env_config.WGSWORKSPACE,
    wessetentity=constants.WESSETENTITY,
    wgssetentity=constants.WGSSETENTITY,
    samplesetname=constants.SAMPLESETNAME,
    purecnsampleset=constants.PURECN_SAMPLESET,
    AllSamplesetName="all",
    taiga_dataset=env_config.TAIGA_CN,
    dataset_description=constants.CNreadme,
    subsetsegs=[
        constants.SAMPLEID,
        "Chromosome",
        "Start",
        "End",
        "Segment_Mean",
        "Num_Probes",
        "Status",
        "Source",
    ],
    bamqc=constants.BAMQC,
    procqc=constants.PROCQC,
    save_dir=constants.WORKING_DIR,
    wesfolder="",
    segmentsthresh=constants.SEGMENTSTHR,
    maxYchrom=constants.MAXYCHROM,
    dryrun=False,
    **kwargs,
):
    """the full CCLE Copy Number post processing pipeline (used only by CCLE)
    see postprocessing() to reproduce most of our analysis and find out about additional parameters
    Args:
        wesrefworkspace (str): wes terra workspace where the ref data is stored
        wgsrefworkspace (str): wgs terra workspace where the ref data is stored
        samplesetname (str): name of the current release
        AllSamplesetName (str, optional): name of the sample set to get the data from (should contain everything). Defaults to 'all'.
        taiga_dataset (str, optional): where to save the output to on taiga. Defaults to env_config.TAIGA_CN.
        dataset_description (str, optional): A long string that will be pushed to taiga to explain the CN dataset. Defaults to constants.CNreadme.
        subsetsegs (list[str], optional): what columns to keep for the segments. Defaults to [constants.SAMPLEID, 'Chromosome', 'Start', 'End', 'Segment_Mean', 'Num_Probes', 'Status', 'Source'].
        bamqc ([type], optional): @see updateTracker. Defaults to constants.BAMQC.
        procqc ([type], optional): @see updateTracker. Defaults to constants.PROCQC.
        source_rename ([type], optional): @see managing duplicates. Defaults to constants.SOURCE_RENAME.
    """
    from taigapy import TaigaClient

    tc = TaigaClient()

    mytracker = track.SampleTracker()
    tracker = mytracker.read_seq_table()

    assert len(tracker) != 0, "broken source for sample tracker"
    pr_table = mytracker.read_pr_table()
    renaming_dict = dict(list(zip(pr_table.MainSequencingID, pr_table.index)))

    mytracker.close_gumbo_client()

    save_dir = save_dir + samplesetname + "/"
    # doing wes
    folder = save_dir + "wes_"
    if wesfolder == "":
        print("doing wes")
        (
            wessegments,
            wesgenecn,
            wesfailed,
            wes_purecn_segments,
            wes_purecn_genecn,
            wes_loh,
            wes_feature_table,
        ) = cn.postProcess(
            wesrefworkspace,
            setEntity=wessetentity,
            sampleset=AllSamplesetName if AllSamplesetName else samplesetname,
            save_output=folder,
            segmentsthresh=segmentsthresh,
            maxYchrom=maxYchrom,
            purecnsampleset=purecnsampleset,
            **kwargs,
        )

    else:
        print("bypassing WES using folder: " + wesfolder)
        wesfailed = h.fileToList(wesfolder + "failed.txt")
        wessegments = pd.read_csv(wesfolder + "segments_all.csv")
        wesgenecn = pd.read_csv(wesfolder + "genecn_all.csv", index_col=0)
        wes_purecn_segments = pd.read_csv(wesfolder + "purecn_segments_all.csv")
        wes_purecn_genecn = pd.read_csv(
            wesfolder + "purecn_genecn_all.csv", index_col=0
        )
        wes_loh = pd.read_csv(wesfolder + "purecn_loh_all.csv", index_col=0)
        wes_feature_table = pd.read_csv(
            wesfolder + "globalGenomicFeatures_all.csv", index_col=0
        )
    # subset and rename to PR-indexed matrices
    wessegments_pr = (
        wessegments[wessegments[constants.SAMPLEID].isin(set(renaming_dict.keys()))]
        .replace({constants.SAMPLEID: renaming_dict})
        .reset_index(drop=True)
    )
    wes_purecn_segments_pr = (
        wes_purecn_segments[
            wes_purecn_segments[constants.SAMPLEID].isin(set(renaming_dict.keys()))
        ]
        .replace({constants.SAMPLEID: renaming_dict})
        .reset_index(drop=True)
    )
    wes_genecn_pr = wesgenecn[wesgenecn.index.isin(set(renaming_dict.keys()))].rename(
        index=renaming_dict
    )
    wes_purecn_genecn_pr = wes_purecn_genecn[
        wes_purecn_genecn.index.isin(set(renaming_dict.keys()))
    ].rename(index=renaming_dict)
    wes_loh_pr = wes_loh[wes_loh.index.isin(set(renaming_dict.keys()))].rename(
        index=renaming_dict
    )
    wes_feature_table_pr = wes_feature_table[
        wes_feature_table.index.isin(set(renaming_dict.keys()))
    ].rename(index=renaming_dict)

    # doing wgs
    print("doing wgs")
    folder = save_dir + "wgs_"
    (
        wgssegments,
        wgsgenecn,
        wgsfailed,
        wgs_purecn_segments,
        wgs_purecn_genecn,
        wgs_loh,
        wgs_feature_table,
    ) = cn.postProcess(
        wgsrefworkspace,
        setEntity=wgssetentity,
        sampleset=AllSamplesetName if AllSamplesetName else samplesetname,
        save_output=folder,
        segmentsthresh=segmentsthresh,
        maxYchrom=maxYchrom,
        purecnsampleset=purecnsampleset,
        **kwargs,
    )

    try:
        track.updateTrackerWGS(
            tracker,
            samplesetname,
            wgsfailed,
            datatype=["wgs", "wes"],
            bamqc=bamqc,
            procqc=procqc,
            refworkspace=wgsrefworkspace,
            dry_run=dryrun,
        )
    except:
        print("no wgs for this sampleset")

    try:
        track.updateTrackerWGS(
            tracker,
            samplesetname,
            list(wesfailed),
            datatype=["wes", "wgs"],
            bamqc=bamqc,
            procqc=procqc,
            refworkspace=wesrefworkspace,
            dry_run=dryrun,
        )
    except:
        print("no wes for this sampleset")

    wgssegments_pr = (
        wgssegments[wgssegments[constants.SAMPLEID].isin(set(renaming_dict.keys()))]
        .replace({constants.SAMPLEID: renaming_dict})
        .reset_index(drop=True)
    )
    wgs_purecn_segments_pr = (
        wgs_purecn_segments[
            wgs_purecn_segments[constants.SAMPLEID].isin(set(renaming_dict.keys()))
        ]
        .replace({constants.SAMPLEID: renaming_dict})
        .reset_index(drop=True)
    )
    wgs_genecn_pr = wgsgenecn[wgsgenecn.index.isin(set(renaming_dict.keys()))].rename(
        index=renaming_dict
    )
    wgs_purecn_genecn_pr = wgs_purecn_genecn[
        wgs_purecn_genecn.index.isin(set(renaming_dict.keys()))
    ].rename(index=renaming_dict)
    wgs_loh_pr = wgs_loh[wgs_loh.index.isin(set(renaming_dict.keys()))].rename(
        index=renaming_dict
    )
    wgs_feature_table_pr = wgs_feature_table[
        wgs_feature_table.index.isin(set(renaming_dict.keys()))
    ].rename(index=renaming_dict)

    print("merging PR-level seg file")
    mergedsegments_pr = wgssegments_pr.append(wessegments_pr).reset_index(drop=True)
    mergedsegments_pr = (
        mergedsegments_pr[
            [
                constants.SAMPLEID,
                "Chromosome",
                "Start",
                "End",
                "SegmentMean",
                "NumProbes",
                "Status",
            ]
        ]
        .sort_values(by=[constants.SAMPLEID, "Chromosome", "Start", "End"])
        .reset_index(drop=True)
    )
    mergedsegments_pr.loc[
        mergedsegments_pr[mergedsegments_pr.Chromosome == "X"].index, "Status"
    ] = "U"

    print("merging PR-level absolute seg file")
    merged_purecn_segments_pr = wgs_purecn_segments_pr.append(
        wes_purecn_segments_pr
    ).reset_index(drop=True)
    merged_purecn_segments_pr = (
        merged_purecn_segments_pr[
            [
                constants.SAMPLEID,
                "Chromosome",
                "Start",
                "End",
                "MajorAlleleAbsoluteCN",
                "MinorAlleleAbsoluteCN",
                "LoHStatus",
            ]
        ]
        .sort_values(by=[constants.SAMPLEID, "Chromosome", "Start", "End"])
        .reset_index(drop=True)
    )

    # merging wes and wgs
    # CDS-ID level
    print("saving merged files")
    folder = save_dir
    mergedsegments = wgssegments.append(wessegments).reset_index(drop=True)
    mergedsegments.to_csv(folder + "merged_segments.csv", index=False)
    mergedcn = (wgsgenecn.append(wesgenecn)).apply(lambda x: np.log2(1 + x))
    mergedcn.to_csv(folder + "merged_genecn.csv")
    merged_purecn_segments = wgs_purecn_segments.append(
        wes_purecn_segments
    ).reset_index(drop=True)
    merged_purecn_segments.to_csv(folder + "merged_absolute_segments.csv", index=False)
    merged_purecn_genecn = wgs_purecn_genecn.append(wes_purecn_genecn)
    merged_purecn_genecn.to_csv(folder + "merged_absolute_genecn.csv")
    merged_loh = wgs_loh.append(wes_loh)
    merged_loh.to_csv(folder + "merged_loh.csv")
    merged_feature_table = wgs_feature_table.append(wes_feature_table)
    merged_feature_table.to_csv(folder + "merged_feature_table.csv")

    # profile-ID level
    mergedsegments_pr.to_csv(folder + "merged_segments_profile.csv", index=False)
    mergedgenecn_pr = wgs_genecn_pr.append(wes_genecn_pr).apply(
        lambda x: np.log2(1 + x)
    )
    mergedgenecn_pr.to_csv(folder + "merged_genecn_profile.csv")
    merged_purecn_segments_pr.to_csv(
        folder + "merged_absolute_segments_profile.csv", index=False
    )
    merged_purecn_genecn_pr = wgs_purecn_genecn_pr.append(wes_purecn_genecn_pr)
    merged_purecn_genecn_pr.to_csv(folder + "merged_absolute_genecn_profile.csv")
    merged_loh_pr = wgs_loh_pr.append(wes_loh_pr)
    merged_loh_pr.to_csv(folder + "merged_loh_profile.csv")
    merged_feature_table_pr = wgs_feature_table_pr.append(wes_feature_table_pr)
    merged_feature_table_pr.to_csv(folder + "merged_feature_table_profile.csv")

    # uploading to taiga
    print("uploading to taiga")
    tc.update_dataset(
        changes_description="new "
        + samplesetname
        + " release! (removed misslabellings, see changelog)",
        dataset_permaname=taiga_dataset,
        upload_files=[
            {
                "path": folder + "merged_segments.csv",
                "name": "merged_segments_withReplicates",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "merged_genecn.csv",
                "name": "merged_gene_cn_withReplicates",
                "format": "NumericMatrixCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "merged_segments_profile.csv",
                "name": "merged_segments_profile",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "merged_genecn_profile.csv",
                "name": "merged_gene_cn_profile",
                "format": "NumericMatrixCSV",
                "encoding": "utf-8",
            },
            # Pure CN outputs
            {
                "path": folder + "merged_absolute_segments.csv",
                "name": "merged_absolute_segments_withReplicates",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "merged_absolute_genecn.csv",
                "name": "merged_absolute_gene_cn_withReplicates",
                "format": "NumericMatrixCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "merged_loh.csv",
                "name": "merged_loh_withReplicates",
                "format": "NumericMatrixCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "merged_feature_table.csv",
                "name": "globalGenomicFeatures_withReplicates",
                "format": "NumericMatrixCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "merged_absolute_segments_profile.csv",
                "name": "merged_absolute_segments_profile",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "merged_absolute_genecn_profile.csv",
                "name": "merged_absolute_gene_cn_profile",
                "format": "NumericMatrixCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "merged_loh_profile.csv",
                "name": "merged_loh_profile",
                "format": "NumericMatrixCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "merged_feature_table_profile.csv",
                "name": "globalGenomicFeatures_profile",
                "format": "NumericMatrixCSV",
                "encoding": "utf-8",
            },
        ],
        dataset_description=dataset_description,
        upload_async=False,
    )
    print("done")
    return wessegments, wgssegments


async def mutationPostProcessing(
    wesrefworkspace=env_config.WESCNWORKSPACE,
    wgsrefworkspace=env_config.WGSWORKSPACE,
    vcfdir=constants.VCFDIR,
    vcf_colname=constants.VCFCOLNAME,
    samplesetname=constants.SAMPLESETNAME,
    AllSamplesetName="all",
    doCleanup=False,
    taiga_description=constants.Mutationsreadme,
    taiga_dataset=env_config.TAIGA_MUTATION,
    bed_locations=constants.GUIDESBED,
    sv_col=constants.SV_COLNAME,
    sv_filename=constants.SV_FILENAME,
    mutcol=constants.MUTCOL_DEPMAP,
    mafcol=constants.MAF_COL,
    run_sv=True,
    run_guidemat=True,
    **kwargs,
):
    """the full CCLE mutations post processing pipeline (used only by CCLE)
    see postprocess() to reproduce our analysis
    Args:
        wesrefworkspace (str, optional): the reference workspace for WES. Defaults to env_config.WESCNWORKSPACE.
        wgsrefworkspace (str, optional): the reference workspace for WGS. Defaults to env_config.WGSWORKSPACE.
        samplesetname (str, optional): the sample set name to use (for the release). Defaults to constants.SAMPLESETNAME.
        AllSamplesetName (str, optional): the sample set to use for all samples. Defaults to 'all'.
        doCleanup (bool, optional): whether to clean up the workspace. Defaults to False.
        taiga_description (str, optional): description of the dataset on taiga. Defaults to constants.Mutationsreadme.
        taiga_dataset (str, optional): taiga folder location. Defaults to env_config.TAIGA_MUTATION.
        mutation_groups (dict, optional): a dict to group mutations annotations into bigger groups. Defaults to constants.MUTATION_GROUPS.
        tokeep_wes (dict, optional): a dict of wes lines that are blacklisted on the tracker due to CN qc but we want to keep their mutation data. Defaults to RESCUE_FOR_MUTATION_WES.
        tokeep_wgs (dict, optional): a dict of wgs lines that are blacklisted on the tracker due to CN qc but we want to keep their mutation data. Defaults to RESCUE_FOR_MUTATION_WGS.
        prev (pd.df, optional): the previous release dataset (to do QC).
            Defaults to ccle =>(tc.get(name=constants.TAIGA_ETERNAL, file='CCLE_mutations')).
    """
    from taigapy import TaigaClient

    tc = TaigaClient()

    wes_wm = dm.WorkspaceManager(wesrefworkspace)
    wgs_wm = dm.WorkspaceManager(wgsrefworkspace)

    # doing wes
    print("DOING WES")
    folder = constants.WORKING_DIR + samplesetname + "/wes_"

    wesmutations, wessvs = mutations.postProcess(
        wes_wm,
        AllSamplesetName if AllSamplesetName else samplesetname,
        save_output=folder,
        sv_col=sv_col,
        sv_filename=sv_filename,
        mafcol=mafcol,
        run_sv=run_sv,
        **kwargs,
    )

    mytracker = track.SampleTracker()
    pr_table = mytracker.read_pr_table()
    renaming_dict = dict(list(zip(pr_table.MainSequencingID, pr_table.index)))
    mytracker.close_gumbo_client()

    wesmutations_pr = wesmutations[
        wesmutations[constants.SAMPLEID].isin(renaming_dict.keys())
    ].replace({constants.SAMPLEID: renaming_dict})

    # doing wgs
    print("DOING WGS")
    folder = constants.WORKING_DIR + samplesetname + "/wgs_"

    wgsmutations, wgssvs = mutations.postProcess(
        wgs_wm,
        sampleset="all",  # AllSamplesetName if AllSamplesetName else samplesetname,
        save_output=folder,
        sv_col=sv_col,
        sv_filename=sv_filename,
        mafcol=mafcol,
        run_sv=run_sv,
        **kwargs,
    )

    wgsmutations_pr = wgsmutations[
        wgsmutations[constants.SAMPLEID].isin(renaming_dict.keys())
    ].replace({constants.SAMPLEID: renaming_dict})

    # merge
    print("merging WES and WGS")
    folder = constants.WORKING_DIR + samplesetname + "/merged_"
    mergedmutations = wgsmutations.append(wesmutations).reset_index(drop=True)
    # some hgnc symbols in the maf are outdated, we are renaming them here and then dropping ones that aren't in biomart
    print("replacing outdated hugo symbols and dropping ones that aren't in biomart")
    hugo_mapping = pd.read_csv(constants.HGNC_MAPPING, sep="\t")
    hugo_mapping = {
        b: a for a, b in hugo_mapping[~hugo_mapping["Previous symbol"].isna()].values
    }

    mybiomart = h.generateGeneNames()
    mybiomart = mybiomart.drop_duplicates("hgnc_symbol", keep="first")

    genes_in_maf = set(mergedmutations.hugo_symbol)
    genes_not_in_biomart = genes_in_maf - set(mybiomart.hgnc_symbol)
    maf_gene_renaming = dict()
    maf_genes_to_drop = []
    for gene in genes_not_in_biomart:
        # if the hugo symbol in maf is outdated, and the new name is in biomart,
        # we will rename it to the new name in the maf
        if gene in hugo_mapping and hugo_mapping[gene] in set(mybiomart.hgnc_symbol):
            maf_gene_renaming[gene] = hugo_mapping[gene]
        # if the hugo symbol can't be found in biomart with or without hugo_mapping,
        # we will drop that gene from the maf
        else:
            maf_genes_to_drop.append(gene)
    mergedmutations = mergedmutations[
        ~mergedmutations.hugo_symbol.isin(maf_genes_to_drop)
    ]
    mergedmutations = mergedmutations.replace({"hugo_symbol": maf_gene_renaming})

    # add entrez id column
    symbol_to_entrez_dict = dict(zip(mybiomart.hgnc_symbol, mybiomart.entrezgene_id))
    mergedmutations["EntrezGeneID"] = mergedmutations["hugo_symbol"].map(
        symbol_to_entrez_dict
    )
    mergedmutations["EntrezGeneID"] = mergedmutations["EntrezGeneID"].fillna("Unknown")
    mergedmutations = mergedmutations.drop(columns=["achilles_top_genes"])
    mergedmutations = mergedmutations.rename(columns=mutcol)

    print("saving merged somatic mutations")
    mergedmutations.to_csv(folder + "somatic_mutations.csv", index=False)

    if run_sv:
        if wgssvs is not None:
            mergedsvs = wgssvs.append(wessvs).reset_index(drop=True)
            mergedsvs.to_csv(folder + "svs.csv", index=False)
            mergedsvs_pr = mergedsvs[
                mergedsvs[constants.SAMPLEID].isin(renaming_dict.keys())
            ].replace({constants.SAMPLEID: renaming_dict})
            print("saving somatic svs")
            mergedsvs_pr.to_csv(folder + "svs_profile.csv", index=False)

    merged = wgsmutations_pr.append(wesmutations_pr).reset_index(drop=True)
    merged["EntrezGeneID"] = merged["hugo_symbol"].map(symbol_to_entrez_dict)
    merged["EntrezGeneID"] = merged["EntrezGeneID"].fillna("Unknown")
    merged = merged.drop(columns=["achilles_top_genes"])
    merged = merged.rename(columns=mutcol)
    merged.to_csv(folder + "somatic_mutations_profile.csv", index=False)

    # making genotyped mutation matrices
    print("creating mutation matrices")
    hotspot_mat, lof_mat, driver_mat = mutations.makeMatrices(merged)
    # add entrez ids to column names
    mybiomart["gene_name"] = [
        i["hgnc_symbol"] + " (" + str(i["entrezgene_id"]).split(".")[0] + ")"
        if not pd.isna(i["entrezgene_id"])
        else i["hgnc_symbol"] + " (Unknown)"
        for _, i in mybiomart.iterrows()
    ]
    symbol_to_symbolentrez_dict = dict(zip(mybiomart.hgnc_symbol, mybiomart.gene_name))
    hotspot_mat = hotspot_mat.rename(columns=symbol_to_symbolentrez_dict)
    lof_mat = lof_mat.rename(columns=symbol_to_symbolentrez_dict)
    driver_mat = driver_mat.rename(columns=symbol_to_symbolentrez_dict)

    hotspot_mat.to_csv(folder + "somatic_mutations_genotyped_hotspot_profile.csv")
    lof_mat.to_csv(folder + "somatic_mutations_genotyped_damaging_profile.csv")
    driver_mat.to_csv(folder + "somatic_mutations_genotyped_driver_profile.csv")

    if run_guidemat:
        # generate germline binary matrix
        wgs_samples = dm.WorkspaceManager(wgsrefworkspace).get_samples()
        wes_samples = dm.WorkspaceManager(wesrefworkspace).get_samples()
        wgs_vcfs = wgs_samples[vcf_colname]
        wes_vcfs = wes_samples[vcf_colname]
        vcflist = (
            wgs_vcfs[~wgs_vcfs.isna()].tolist() + wes_vcfs[~wes_vcfs.isna()].tolist()
        )
        vcflist = [v for v in vcflist if v.startswith("gs://")]

        print("generating germline binary matrix")
        germline_mats = mut.generateGermlineMatrix(
            vcflist,
            vcfdir=vcfdir,
            savedir=constants.WORKING_DIR + samplesetname + "/",
            filename="binary_mutguides.tsv.gz",
            bed_locations=bed_locations,
        )
        for lib, mat in germline_mats.items():
            # merging wes and wgs
            print("renaming merged wes and wgs germline matrix for library: ", lib)
            germline_mat_noguides = mat.iloc[:, 4:]

            # transform from CDSID-level to PR-level
            whitelist_cols = [
                x for x in germline_mat_noguides.columns if x in renaming_dict
            ]
            whitelist_germline_mat = germline_mat_noguides[whitelist_cols]
            mergedmat = whitelist_germline_mat.rename(columns=renaming_dict)

            mergedmat = mergedmat.astype(bool).astype(int)
            sorted_mat = mat.iloc[:, :4].join(mergedmat)
            sorted_mat["end"] = sorted_mat["end"].astype(int)
            print("saving merged binary matrix for library: ", lib)
            sorted_mat.to_csv(
                folder + "binary_germline" + "_" + lib + ".csv", index=False
            )
    # uploading to taiga
    tc.update_dataset(
        changes_description="new " + samplesetname + " release!",
        dataset_permaname=taiga_dataset,
        upload_files=[
            {
                "path": folder + "somatic_mutations_genotyped_driver_profile.csv",
                "name": "somaticMutations_genotypedMatrix_driver_profile",
                "format": "NumericMatrixCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "somatic_mutations_genotyped_hotspot_profile.csv",
                "name": "somaticMutations_genotypedMatrix_hotspot_profile",
                "format": "NumericMatrixCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "somatic_mutations_genotyped_damaging_profile.csv",
                "name": "somaticMutations_genotypedMatrix_damaging_profile",
                "format": "NumericMatrixCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "somatic_mutations_profile.csv",
                "name": "somaticMutations_profile",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "somatic_mutations.csv",
                "name": "somaticMutations_withReplicates",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "merged_binary_germline_avana.csv",
                "name": "binary_mutation_avana",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "merged_binary_germline_ky.csv",
                "name": "binary_mutation_ky",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "merged_binary_germline_humagne.csv",
                "name": "binary_mutation_humagne",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "svs.csv",
                "name": "structuralVariants_withReplicates",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
            {
                "path": folder + "svs_profile.csv",
                "name": "structuralVariants_profile",
                "format": "TableCSV",
                "encoding": "utf-8",
            },
        ],
        upload_async=False,
        dataset_description=taiga_description,
    )
