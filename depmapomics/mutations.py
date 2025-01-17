from depmapomics import constants
from genepy.utils import helper as h
import os
import pandas as pd
from collections import Counter
import pandas as pd
from genepy.epigenetics import chipseq as chip
from itertools import repeat
import multiprocessing
import subprocess


def annotateLikelyImmortalized(
    maf,
    sample_col=constants.SAMPLEID,
    genome_change_col="dna_change",
    chrom_col="chrom",
    pos_col="pos",
    hotspotcol="cosmic_hotspot",
    max_recurrence=constants.IMMORTALIZED_THR,
):
    """annotateLikelyImmortalized annotates the maf file with the likely immortalized mutations

    Based on occurence accross samples

    Args:
        maf (pandas.DataFrame): the maf file with columns: sample_col, genome_change_col, TCGAlocs
        sample_col (str): the column name of the sample id
        genome_change_col (str, optional): the column name of the genome change. Defaults to "Genome_Change".
        TCGAlocs (list, optional): the column names of the counts that would make the mutation non immortalization induced. Defaults to ['TCGAhsCnt', 'COSMIChsCnt'].
        max_recurrence (float, optional): the maximum recurrence rate to call immortalize. Defaults to 0.05.
        min_tcga_true_cancer (int, optional): the minimum number of TCGA true cancer samples to not call immortalize. Defaults to 5.

    Returns:
        pandas.DataFrame: the maf file with the added column: immortalized
    """
    maf["is_likely_immortalization"] = False
    maf["combined_mut"] = (
        maf[chrom_col] + "_" + maf[pos_col].astype(str) + "_" + maf[genome_change_col]
    )
    leng = len(set(maf[sample_col]))
    maf[
        (maf[hotspotcol] != "Y")
        & (
            maf["combined_mut"].isin(
                [
                    k
                    for k, v in Counter(maf["combined_mut"].tolist()).items()
                    if v > max_recurrence * leng
                ]
            )
        )
    ]["LikelyImmortalized"] = True
    maf = maf.drop(columns=["combined_mut"])
    return maf


def addAnnotation(maf, NCBI_Build="37", Strand="+"):
    """
    adds NCBI_Build and Strand annotation on the whole maf file

    Args:
        maf (pandas.DataFrame): the maf file with columns: sample_col, genome_change_col, TCGAlocs
        NCBI_Build (str, optional): the NCBI build. Defaults to "37".
        Strand (str, optional): the strand. Defaults to "+".

    Returns:
        pandas.DataFrame: the maf file with the added columns: NCBI_Build, Strand
    """
    maf["NCBI_Build"] = NCBI_Build
    maf["Strand"] = Strand
    return maf


def makeMatrices(
    maf,
    homin=0.95,
    id_col=constants.SAMPLEID,
    hotspot_col=constants.HOTSPOT_COL,
    hugo_col=constants.HUGO_COL,
    lof_col=constants.LIKELY_LOF_COL,
    ccle_deleterious_col=constants.CCLE_DELETERIOUS_COL,
    civic_col=constants.CIVIC_SCORE_COL,
    hess_col=constants.HESS_COL,
):
    """generates genotyped hotspot, driver and damaging mutation matrices

    Returns:
        hotspot_mat (pd.DataFrame): genotyped hotspot mutation matrix. 0 == not damaging, 1 == heterozygous, 2 == homozygous
        lof_mat (pd.DataFrame): genotyped damaging mutation matrix. 0 == not damaging, 1 == heterozygous, 2 == homozygous
        driver_mat (pd.DataFrame): genotyped driver mutation matrix. 0 == not driver, 1 == heterozygous, 2 == homozygous
    """
    print("generating genotyped driver and damaging mutation matrix")
    gene_names = list(maf[hugo_col].unique())
    hotspot_mat = pd.DataFrame(columns=gene_names)
    lof_mat = pd.DataFrame(columns=gene_names)
    driver_mat = pd.DataFrame(columns=gene_names)
    sample_ids = list(maf[id_col].unique())
    le = len(sample_ids)
    for j in range(le):
        h.showcount(j, le)
        sample = sample_ids[j]
        subset_maf = maf[maf[id_col] == sample]
        # hotspot
        hotspot = subset_maf[subset_maf[hess_col] == "Y"]
        homhotspot = set(hotspot[hotspot["GT"] == "1|1"][hugo_col])
        for dup in h.dups(hotspot[hugo_col]):
            if hotspot[hotspot[hugo_col] == dup]["AF"].astype(float).sum() >= homin:
                homhotspot.add(dup)
        hethotspot = set(hotspot[hugo_col]) - homhotspot
        hotspot_mat.loc[sample, homhotspot] = "2"
        hotspot_mat.loc[sample, hethotspot] = "1"
        # damaging
        lof = subset_maf[
            (subset_maf[lof_col] == "Y") | (subset_maf[ccle_deleterious_col] == "Y")
        ]
        homlof = set(lof[lof["GT"] == "1|1"][hugo_col])
        for dup in h.dups(lof[hugo_col]):
            if lof[lof[hugo_col] == dup]["AF"].astype(float).sum() >= homin:
                homlof.add(dup)
        hetlof = set(lof[hugo_col]) - homlof
        lof_mat.loc[sample, homlof] = "2"
        lof_mat.loc[sample, hetlof] = "1"
        # driver
        driver = subset_maf[
            ((~subset_maf[civic_col].isnull()) & (subset_maf[civic_col] != 0))
            | (subset_maf[hess_col] == "Y")
        ]
        homdriv = set(driver[driver["GT"] == "1|1"][hugo_col])
        for dup in h.dups(driver[hugo_col]):
            if driver[driver[hugo_col] == dup]["AF"].astype(float).sum() >= homin:
                homdriv.add(dup)
        hetdriv = set(driver[hugo_col]) - homdriv
        driver_mat.loc[sample, homdriv] = "2"
        driver_mat.loc[sample, hetdriv] = "1"
    hotspot_mat = hotspot_mat.dropna(axis="columns", how="all")
    lof_mat = lof_mat.dropna(axis="columns", how="all")
    driver_mat = driver_mat.dropna(axis="columns", how="all")
    hotspot_mat = hotspot_mat.fillna(0).astype(int)
    lof_mat = lof_mat.fillna(0).astype(int)
    driver_mat = driver_mat.fillna(0).astype(int)

    return hotspot_mat, lof_mat, driver_mat


def managingDuplicates(samples, failed, datatype, tracker):
    """
    managingDuplicates manages the duplicates in the samples

    by only keeping the ones that are not old and did not fail QC

    Args:
        samples (list): the list of samples
        failed (list): the list of failed samples
        datatype (str): the data type to look at in the sample tracker
        tracker (pd.df): the sample tracker

    Returns:
        dict: the renaming dict
    """
    # selecting the right arxspan id (latest version)
    renaming = tracker.removeOlderVersions(
        names=samples,
        refsamples=tracker[tracker.datatype == datatype],
        priority="prioritized",
    )

    # reparing QC when we have a better duplicate
    ref = pd.DataFrame(tracker[tracker.datatype == datatype]["arxspan_id"])
    replace = 0
    for val in failed:
        if val in list(renaming.keys()):
            a = ref[ref.arxspan_id == ref.loc[val, "arxspan_id"]].index
            for v in a:
                if v not in failed:
                    renaming[v] = renaming.pop(val)
                    replace += 1
                    break
    print("could replace:")
    print(replace)
    return renaming


def aggregateMAFs(
    wm,
    sampleset="all",
    mafcol=constants.MAF_COL,
    keep_cols=constants.MUTCOL_DEPMAP,
):
    """aggregate MAF files from terra

    Args:
        refworkspace (str): the reference workspace
        sampleset (str, optional): the sample set to use. Defaults to 'all'.
        mutCol (str, optional): the MAF column name. Defaults to "somatic_maf".
        keep_cols (list, optional): which columns to keep in the aggregate MAF file. Defaults to constants.MUTCOL_DEPMAP

    Returns:
        aggregated_maf (df.DataFrame): aggregated MAF
    """
    print("aggregating MAF files")
    sample_table = wm.get_samples()
    samples_in_set = wm.get_sample_sets().loc[sampleset]["samples"]
    sample_table = sample_table[sample_table.index.isin(samples_in_set)]
    sample_table_valid = sample_table[~sample_table[mafcol].isna()]
    na_samples = set(sample_table.index) - set(sample_table_valid.index)
    print(str(len(na_samples)) + " samples don't have corresponding maf: ", na_samples)
    all_mafs = []
    le = len(sample_table_valid)
    counter = 0
    for name, row in sample_table_valid.iterrows():
        # prints out progress bar
        h.showcount(counter, le)
        counter += 1
        maf = pd.read_csv(row[mafcol])
        maf[constants.SAMPLEID] = name
        # >1 because of the hess_signature typo in input mafs
        # can be 0 once the type is fixed upstream
        if len(set(keep_cols.keys()) - set(maf.columns)) > 1:
            print(name + " is missing columns")
        all_mafs.append(maf)
    all_mafs = pd.concat(all_mafs)
    return all_mafs


def aggregateSV(
    wm,
    sampleset="all",
    sv_colname=constants.SV_COLNAME,
    sv_renaming=constants.SV_COLRENAME,
    save_output="",
    save_filename="",
):
    """aggregate SVs pulled from a terra workspace

    Args:
        refworkspace (str): terra workspace where the ref data is stored
        sampleids (list[str]): list of sequencing IDs
        all_sv_colname (str): name of column in terra workspace that contains sv output files. Defaults to "filtered_annotated_sv"
        save_output (str, optional): whether to save our data. Defaults to "".

    Returns:

    """
    print("aggregating SVs")
    sample_table = wm.get_samples()
    samples_in_set = wm.get_sample_sets().loc[sampleset]["samples"]
    sample_table = sample_table[sample_table.index.isin(samples_in_set)]
    sample_table_valid = sample_table[~sample_table[sv_colname].isna()]
    na_samples = set(sample_table.index) - set(sample_table_valid.index)
    print(str(len(na_samples)) + " samples don't have corresponding sv: ", na_samples)
    all_svs = []
    for name, row in sample_table_valid.iterrows():
        sv = pd.read_csv(row[sv_colname], sep="\t")
        sv[constants.SAMPLEID] = name
        sv = sv.rename(columns=sv_renaming)
        all_svs.append(sv)
    all_svs = pd.concat(all_svs)
    print("saving aggregated SVs")
    all_svs.to_csv(save_output + save_filename, sep="\t", index=False)
    return all_svs


def postProcess(
    wm,
    sampleset="all",
    mafcol=constants.MAF_COL,
    save_output=constants.WORKING_DIR,
    sv_col=constants.SV_COLNAME,
    sv_filename=constants.SV_FILENAME,
    sv_renaming=constants.SV_COLRENAME,
    run_sv=True,
):
    """Calls functions to aggregate MAF files, annotate likely immortalization status of mutations,
    and aggregate structural variants (SVs)

    Args:
        wm (dalmatian.WorkspaceManager): workspace manager of the reference workspace
        sampleset (str, optional): the sample set to use. Defaults to 'all'.
        mutCol (str, optional): the mutation column name. Defaults to "mut_AC".
        save_output (str, optional): the output file name to save results into. Defaults to "".
        doCleanup (bool, optional): whether to clean up the workspace. Defaults to False.
        rename_cols (dict, optional): the rename dict for the columns.
            Defaults to {"i_ExAC_AF": "ExAC_AF",
                        "Tumor_Sample_Barcode": constants.SAMPLEID,
                        "Tumor_Seq_Allele2": "Tumor_Allele"}.

    Returns:
        pandas.DataFrame: the maf file with the added columns: variant_annotation
    """
    h.createFoldersFor(save_output)
    print("loading from Terra")
    # if save_output:
    # terra.saveConfigs(refworkspace, save_output + 'config/')
    mutations = aggregateMAFs(
        wm,
        sampleset=sampleset,
        mafcol=mafcol,
        keep_cols=constants.MUTCOL_DEPMAP,
    )

    # print("annotating likely immortalized status")
    # mutations = annotateLikelyImmortalized(
    #     mutations, hotspotcol="cosmic_hotspot", max_recurrence=constants.IMMORTALIZED_THR,
    # )

    print("saving somatic mutations (all)")
    mutations.to_csv(save_output + "somatic_mutations_all.csv", index=None)
    print("done")

    svs = None
    if run_sv:
        svs = aggregateSV(
            wm,
            sampleset=sampleset,
            sv_colname=sv_col,
            save_output=save_output,
            save_filename=sv_filename,
            sv_renaming=sv_renaming,
        )
        print("saving svs (all)")
        svs.to_csv(save_output + "svs_all.csv", index=None)

    return mutations, svs


def mapBed(file, vcfdir, guide_df):
    """map mutations in one vcf file to regions in the guide bed file"""

    bed = pd.read_csv(
        vcfdir + file,
        sep="\t",
        header=None,
        names=["chrom", "start", "end", "foldchange"],
    )
    bed["foldchange"] = 1
    name = file.split("/")[-1].split(".")[0].split("_")[1]
    if len(bed) == 0:
        return (name, None)
    val = chip.putInBed(guide_df, bed, mergetype="sum")

    return (name, val)


def generateGermlineMatrix(
    vcfs,
    vcfdir,
    savedir=constants.WORKING_DIR + constants.SAMPLESETNAME + "/",
    filename="binary_mutguides.tsv.gz",
    bed_locations=constants.GUIDESBED,
    cores=16,
):
    """generate profile-level germline mutation matrix for achilles' ancestry correction. VCF files are generated
    using the CCLE pipeline on terra
    Args:
        vcfs (list): list of vcf file locations (gs links)
        vcfdir (str, optional): directory where vcf files are saved.
        savedir (str, optional): directory where output germline matrices are saved.
        bed_location (str, optional): location of the guides bed file.
        vcf_colname (str, optional): vcf column name on terra.
        cores (int, optional): number of cores in parallel processing.

    Returns:
        sorted_mat (pd.DataFrame): binary matrix where each row is a region in the guide, and each column corresponds to a profile
    """
    # check if bcftools is installed
    print("generating germline matrix")
    print(
        "bcftools is required in order to generate the matrix. Checking if bcftools is installed..."
    )
    try:
        subprocess.call(["bcftools"])
    except FileNotFoundError:
        raise RuntimeError("bcftools not installed!")

    h.createFoldersFor(savedir)
    # load vcfs from workspace using dalmatian
    h.createFoldersFor(vcfdir)

    # save vcfs from workspace locally,
    # and run bcftools query to transform vcfs into format needed for subsequent steps
    # only including regions in the guide bed file

    cmds = []
    for lib, _ in bed_locations.items():
        h.createFoldersFor(vcfdir + lib + "/")
    for sam in vcfs:
        cmd = (
            "gsutil cp "
            + sam
            + " "
            + vcfdir
            + sam.split("/")[-1]
            + " && gsutil cp "
            + sam
            + ".tbi"
            + " "
            + vcfdir
            + sam.split("/")[-1]
            + ".tbi && "
        )
        for lib, fn in bed_locations.items():
            cmd += (
                "bcftools query\
                    --exclude \"FILTER!='PASS'&GT!='mis'&GT!~'\.'\"\
                    --regions-file "
                + fn
                + " \
                    --format '%CHROM\\t%POS\\t%END\\t%ALT{0}\n' "
                + vcfdir
                + sam.split("/")[-1]
                + " > "
                + vcfdir
                + lib
                + "/"
                + "loc_"
                + sam.split("/")[-1].split(".")[0]
                + ".bed && "
            )
        cmd += "rm " + vcfdir + sam.split("/")[-1] + "*"
        cmds.append(cmd)

    print("running bcftools index and query")
    h.parrun(cmds, cores=cores)
    print("finished running bcftools index and query")

    pool = multiprocessing.Pool(cores)
    binary_matrices = dict()
    for lib, fn in bed_locations.items():
        print("mapping to library: ", lib)
        guides_bed = pd.read_csv(
            fn,
            sep="\t",
            header=None,
            names=["chrom", "start", "end", "foldchange"],
        )
        res = pool.starmap(
            mapBed,
            zip(
                os.listdir(vcfdir + lib + "/"),
                repeat(vcfdir + lib + "/"),
                repeat(guides_bed),
            ),
        )
        sorted_guides_bed = guides_bed.sort_values(
            by=["chrom", "start", "end"]
        ).reset_index(drop=True)
        print("done pooling")
        for name, val in res:
            if val is not None:
                sorted_guides_bed[name] = val
        sorted_guides_bed = sorted_guides_bed.rename(columns={"foldchange": "sgRNA"})
        print("saving binary matrix for library: ", lib)
        sorted_guides_bed.to_csv(savedir + lib + "_" + filename, index=False)
        binary_matrices[lib] = sorted_guides_bed

    return binary_matrices
