import argparse
import sys
import os
import datetime
import json
import time
import mistune
from src.preprocess_fastqs import reheader_fastqs, check_library_prep
from src.umi_error_correct import get_umi_families, umi_datafile
from src.generate_consensus import generate_consensus_output
from src.generate_vcf import WriteVCF
from src.run_analyses import MergeDataFiles, MergeConsensusFiles, MergeUmiFiles, submit_jobs
from src.utilities import CheckRegionFormat, GetOutputDir, GetInputFiles, GetThresholds, GetFamSize, \
 FormatRegion, GroupQCWriter, CreateDirTree, CheckFileContent, DropEmptyFiles, CheckFilePath, ConvertArgToBool
from src.generate_plots import PlotMeanFamSize, PlotNonRefFreqData, PlotConsDepth,\
 PlotParentsToChildrenCounts, PlotParentFreq, PlotNetworkDegree, PlotUMiFrequency,\
 GetUmiCountFromPreprocessing, PlotFamSizeReadDepth, PlotReadDepth, GetIndividualUmiInfo,\
 PlotIncorrectReads, PlotDataPerRegion
from src.generate_report import WriteReport   
 
import matplotlib.pyplot as plt
import numpy as np
import scipy.ndimage   


"""
debarcer.py - main interface for Debarcer
=========================================

Purpose
-------
Debarcer (De-Barcoding and Error Correction) is a package 
for working with next-gen sequencing data that contains
molecular barcodes.

Authors: Alexandra Bodak, Lawrence Heisler, Richard Jovelin, Isha Warikoo 
Copyright (c) 2018 GSI, Ontario Institute for Cancer Research
"""

def timestamp():
    """Returns the current time in a nice format for log files."""
    return "[{}] ".format(str(datetime.datetime.now()).split('.')[0])


def preprocess_reads(args):
    '''
    (list) -> None
    Preprocesses fastq files by removing UMIs from reads, appending them to 
    the read names and writing new fastqs and also write QC reports in a Stats directory
	 
    :param outdir: Directory where new fastqs are written. From command or config
    :param read1: Path to first FASTQ file
    :param read2: Path to second FASTQ file
    :param read3: Path to third FASTQ file
    :param prepname: Name of the library preparation
    :param prepfile: Path to the library preparation ini file. From command or config
    :param config: Path to the config file. 
    :param prefix: Prefix for naming umi-reheradered fastqs 
    '''
        
    # get output directory from the config or command. set to current dir if not provided
    outdir = GetOutputDir(args.config, args.outdir)
    # create outputdir if doesn't exist
    if os.path.isdir(outdir) == False:
        if os.path.isfile(outdir) == True:
            raise ValueError('ERR: Output directory cannot be a file')
        else:
            os.makedirs(outdir)
    
    # get input prep file from config or command
    prepfile = GetInputFiles(args.config, args.prepfile, 'prep_file')
    
    # check library prep format
    check_library_prep(args.prepname, prepfile)
        
    # check that files are valid
    for i in [args.read1, args.read2, args.read3]:
        # check that argument (or file) is provided/exists 
        if i:
            # check if provided file is file
            if os.path.isfile(i) == False:
                # raise error and exit
                raise ValueError('ERR: prepfile is not a valid file')
                sys.exit(1)
    
    # reheader fastqs and add umi in new fastqs header
    # get the number of correct, incorrect and total reads and list of umi sequences
    Correct, Incorrect, Total, UmiSequences = reheader_fastqs(args.read1, outdir, args.prepname, prepfile, r2=args.read2, r3=args.read3, prefix=args.prefix)
	 
    # create subdirectoy structure
    CreateDirTree(outdir)
    
    # write json with correct/incorrect reads
    D = {'Total': Total, 'Correct': Correct, 'Incorrect': Incorrect}
    with open(os.path.join(outdir, 'Stats/Read_Info.json'), 'w') as newfile:
        json.dump(D, newfile, sort_Keys=True, indent=4)
    
    # write table with umi sequences counts
    D = {}
    for i in UmiSequences:
        D[i] = UmiSequences.count(i)
    Outpufile = os.path.join(outdir, 'Stats/Umi_counts.txt')
    newfile = open(Outpufile, 'w')
    newfile.write('\t'.join(['Umi', 'Count']) + '\n')
    for i in D:
        newfile.write('\t'.join([i, str(D[i])]) + '\n')
    newfile.close()



def group_umis(args):
    '''
    (list) -> None
       
    :param outdir: Output directory where subdirectories are created
    :param region: A string with region coordinates chrN:posA-posB. posA and posB are 1-based included
    :param bamfile: Path to the bam file
    :param config: Path to your config file
    :param distthreshold: Hamming distance threshold for connecting parent-children umis
    :param postthreshold: Distance threshold in bp for defining families within groups
    :param ignore: Keep the most abundant family and ignore families at other positions within each group if True. Default is False
    :param truncate: Skip reads overlapping with the genomic interval if True. Default is False
        
    Groups by hamming distance and form families based on physical distances within groups
    '''
    
    
    print('group', 'ignore',  args.ignore, type(args.ignore))
    print('group', 'ignore', 'bool', isinstance(args.ignore, bool), 'str', isinstance(args.ignore, str))
    
    
    
    # get output directory from the config or command. set to current dir if not provided
    outdir = GetOutputDir(args.config, args.outdir)
    # create outputdir if doesn't exist
    if os.path.isdir(outdir) == False:
        if os.path.isfile(outdir) == True:
            raise ValueError('ERR: Output directory cannot be a file')
        else:
            os.makedirs(outdir)
    
    # create subdirectoy structure
    CreateDirTree(outdir)

    # get input bam from config or command
    bam_file = GetInputFiles(args.config, args.bamfile, 'bam_file')
    
    # check that region is properly formatted
    region = args.region
    CheckRegionFormat(region)
    # get chromosome
    contig = region.split(":")[0]
    # get 1-based inclusive region coordinates   
    region_start, region_end = int(region.split(":")[1].split("-")[0]), int(region.split(":")[1].split("-")[1])
    # convert coordinates to 0-based hal opened coordinates
    region_start = region_start -1
    
    # get umi position and distance thresholds 
    pos_threshold = GetThresholds(args.config, 'umi_family_pos_threshold', args.postthreshold)
    dist_threshold = GetThresholds(args.config, 'umi_edit_distance_threshold', args.distthreshold)
                
    print(timestamp() + "Grouping UMIs...")
    
    # Generate UMI families within groups using the position of the most frequent umi as reference for each family
    # keep the most abundant family within group and ignore others if args.ignore is True
    umi_families, umi_groups, umi_positions, mapped_reads = get_umi_families(contig, region_start, region_end, bam_file, pos_threshold, dist_threshold, args.ignore, args.truncate)
    
    # get the number of parent umis, number of children and number of parent given a number of children
    filename= os.path.join(outdir, 'Datafiles/datafile_{}.csv'.format(region))
    header = ['CHR', 'START', 'END', 'PTU', 'CTU', 'CHILD_NUMS', 'FREQ_PARENTS']
    # use 1-based inclusive coordinates in datafile output
    info = [contig, str(region_start + 1), str(region_end)] + umi_datafile(umi_groups)
    with open(filename, 'w') as newfile:
        newfile.write('\t'.join(header) + '\n')
        newfile.write('\t'.join(info) + '\n')
    
    # save umi families as a json. positions in the json are 0-based half opened
    umi_file = os.path.join(outdir, 'Umifiles/{0}.json'.format(region))
    with open(umi_file, 'w') as newfile:
        json.dump(umi_families, newfile, sort_keys = True, indent=4)
    
    # write a summary file of UMI relationships and count for each individual umi before grouping
    Outputfile = os.path.join(outdir, 'Stats/UMI_relationships_{0}.txt'.format(region))
    GroupQCWriter(umi_positions, Outputfile)
    
    # save information about individual UMIs as a json in Stats directory
    umi_file = os.path.join(outdir, 'Stats/Umis_{}_before_grouping.json'.format(region))
    with open(umi_file, 'w') as newfile:
        json.dump(umi_positions, newfile, sort_keys = True, indent=4)
    
    # save counts of unmapped and mapped reads as a json in Stats directory
    read_file = os.path.join(outdir, 'Stats/Mapped_read_counts_{}.json'.format(region))
    with open(read_file, 'w') as newfile:
        json.dump(mapped_reads, newfile, sort_keys = True, indent=4)
        
    print(timestamp() + "UMI grouping complete. CSV files written to {0}.".format(os.path.join(outdir, 'Datafiles')))
    print(timestamp() + "UMI grouping complete. UMI files written to {0}.".format(os.path.join(outdir, 'Umifiles')))
    print(timestamp() + "UMI grouping complete. QC files written to {0}.".format(os.path.join(outdir, 'Stats')))


def collapse(args):
    '''
    (list) -> None
    
    :param config: Path to the config file
    :param outdir: Output directory where subdirectories are created
    :param bamfile: Path to the BAM file
    :param reference: Path to the reference genome
    :param region: Region coordinates (1-based included) to search for UMIs (eg. chrN:posA-posB)
    :param umifile: Path to the .umis file
    :param famsize: Comma-separated list of minimum umi family size to collapase on
    :param countthreshold: Base count threshold in pileup column
    :param percentthreshold: Base percent threshold in pileup column
    :param postthreshold: Umi position threshold for grouping umis together
    :param maxdepth: Maximum read depth. Default is 1000000
    :param truncate: Only consider pileup columns in given region. Default is False
    :param ignoreorphans: Ignore orphans (paired reads that are not in a proper pair). Default is True
    :param stepper: Controls how the iterator advances. Accepeted values:
                    'all': skip reads with following flags: BAM_FUNMAP, BAM_FSECONDARY, BAM_FQCFAIL, BAM_FDUP
                    'nofilter': uses every single read turning off any filtering
        
    Base collapses from given BAM and umi family file
    '''
    
    
    
    
    print('collapse:')
    print('truncate', args.truncate, type(args.truncate))
    print('collapse:', 'truncate', 'bool:', isinstance(args.truncate, bool), 'str',  isinstance(args.truncate, str)) 
    print('collapse:', 'orphans', args.ignoreorphans, type(args.ignoreorphans))
    print('collapse:', 'orphans', 'bool:', isinstance(args.ignoreorphans, bool), 'str',  isinstance(args.ignoreorphans, str)) 
    
    
       
    
    
    # get output directory from the config or command. set to current dir if not provided
    outdir = GetOutputDir(args.config, args.outdir)
    # create outputdir if doesn't exist
    if os.path.isdir(outdir) == False:
        if os.path.isfile(outdir) == True:
            raise ValueError('ERR: Output directory cannot be a file')
        else:
            os.makedirs(outdir)
    
    # create subdirectoy structure
    CreateDirTree(outdir)

    # get input bam from config or command
    bam_file = GetInputFiles(args.config, args.bamfile, 'bam_file')

    # check that region is properly formatted
    region = args.region
    CheckRegionFormat(region)
    # get chromosome 
    contig = region.split(":")[0]
    # get 1-based inclusive region coordinates
    region_start, region_end = int(region.split(":")[1].split("-")[0]), int(region.split(":")[1].split("-")[1])
    # convert coordinates to 0-based half opened coordinates
    region_start = region_start -1
    
    # load json with count of umi families per position and umi group
    try:
        infile = open(args.umifile)
        umi_families = json.load(infile)
        infile.close()
    except:
        raise ValueError("ERR: Unable to load umi json file")
        
    print(timestamp() + "Generating consensus...")


    # get percent threshold 
    consensus_threshold = GetThresholds(args.config, 'percent_consensus_threshold', args.percentthreshold)
    # get count threshold
    count_threshold = GetThresholds(args.config, 'count_consensus_threshold', args.countthreshold)
    # get umi position threshold 
    pos_threshold = GetThresholds(args.config, 'umi_family_pos_threshold', args.postthreshold)
    
    # get reference
    reference = GetInputFiles(args.config, args.reference, 'reference_file')
    
    # get comma-separated list of minimum family sizes 
    fam_size = GetFamSize(args.config, args.famsize)
    
    # write consensus output file
    ConsDir = os.path.join(outdir, 'Consfiles')
    generate_consensus_output(reference, contig, region_start, region_end, bam_file, umi_families, ConsDir, fam_size, pos_threshold, consensus_threshold, count_threshold, max_depth=args.maxdepth, truncate=args.truncate, ignore_orphans=args.ignoreorphans, stepper=args.stepper)
 
    print(timestamp() + "Consensus generated. Consensus file written to {}.".format(ConsDir))


def VCF_converter(args):
    '''
    (list) --> None
    
    :param config: Path to the config file
    :param outdir: Output directory where subdirectories are created
    
    param consfile: Path to the consensus file (merged or not)
    :param outputfile: Path to the output VCF file
    :param reference" Path to the reference genome 
    :param famsize: Minimum umi family size to collapse umi
    :param ref_threshold: Maximum reference frequency (in %) to consider alternative variants
                          (ie. position with ref freq <= ref_threshold is considered variable)
    :param alt_threshold: Minimum allele frequency (in %) to consider an alternative allele at a variable position 
                          (ie. allele freq >= alt_threshold and ref freq <= ref_threshold --> record alternative allele)
    :param filter_threshold: Minimum number of reads to pass alternative variants 
                             (ie. filter = PASS if variant depth >= alt_threshold)
    
    Converts consensus files into VCF format
    '''

    # get output directory from the config or command. set to current dir if not provided
    outdir = GetOutputDir(args.config, args.outdir)
    # create outputdir if doesn't exist
    if os.path.isdir(outdir) == False:
        if os.path.isfile(outdir) == True:
            raise ValueError('ERR: Output directory cannot be a file')
        else:
            os.makedirs(outdir)
    
    # get the subdirectory with consensus files
    ConsDir = os.path.join(outdir, 'Consfiles')
    if os.path.isdir(ConsDir) == False:
        raise ValueError('ERR: {0} is not a valid directory'.format(ConsDir))
    
    # make a list of consensus files
    ConsFiles = [os.path.join(ConsDir, i) for i in os.listdir(ConsDir) if i[-5:] == '.cons' in i]
    # remove empty files in place and print a warning
    DropEmptyFiles(ConsFiles)
    # check that paths to files are valid. raise ValueError if file invalid
    CheckFilePath(ConsFiles)
    
    # create vcf dir if doesn't exist already
    VCFDir = os.path.join(outdir, 'VCFfiles')
    if os.path.isdir(VCFDir) == False:
        os.mkdir(VCFDir)
    
    # get reference threshold
    ref_threshold = GetThresholds(args.config, 'percent_ref_threshold', args.refthreshold)
    # get allele threshold
    alt_threshold = GetThresholds(args.config, 'percent_alt_threshold', args.altthreshold)
    # get filter threshold
    filter_threshold = GetThresholds(args.config, 'filter_threshold', args.filterthreshold)
    
    # get minimum umi family sizes
    family_sizes = list(map(lambda x: int(x.strip()), args.famsize.split(',')))
    # generate vcf for famsize = 0. this is because 0 can be omitted during collapse
    if 0 not in family_sizes:
        family_sizes.append(0)
        
    print(timestamp() + "Generating VCFs...")

    # loop over consensus files
    for filename in ConsFiles:
        # loop over family sizes
        for family in family_sizes:
            # write a VCF per family size and consensus file
            outputfile = os.path.join(VCFDir, os.path.basename(filename)[:-5] + '_umifam_' + str(family) + '.vcf')
            WriteVCF(filename, outputfile, args.reference, family, ref_threshold, alt_threshold, filter_threshold)

    print(timestamp() + "VCFs generated. VCF files written to {0}.".format(VCFDir))


def merge_files(args):
    '''
    (list) -> None
    
    :param outdir: Output directory where subdirectories are created
    :param datatype: Type of files to be merged.
                     Valid options are 'datafiles', 'consensusfiles', 'umifiles'
    
    Grab and merge all files of given datatype in corresponding subdirectory
    '''
    
    # check which files need to be merged
    if args.datatype == 'datafiles':
        MergeDataFiles(args.directory)
    elif args.datatype == 'consensusfiles':
        MergeConsensusFiles(args.directory)
    elif args.datatype == 'umifiles':
        MergeUmiFiles(args.directory)

def run_scripts(args):
    '''
    (list) -> None
    
    :param outdir: Output directory where subdirectories are created
    :param config: Path to the config file
    :param bamfile: Path to the BAM file
    :param reference: Path to the refeence genome
    :param famsize: Comma-separated list of minimum umi family size to collapase on
    :param bedfile: Path to the bed file
    :param count_threshold: Base count threshold in pileup column
    :param consensus_threshold: Majority rule consensus threshold in pileup column
    :param post_threshold: Umi position threshold for grouping umis together
    :param dist_threshold: Hamming distance threshold for connecting parent-children umis
    :param ref_threshold: Maximum reference frequency (in %) to consider alternative variants
                          (ie. position with ref freq <= ref_threshold is considered variable)
    :param alt_threshold: Minimum allele frequency (in %) to consider an alternative allele at a variable position 
                          (ie. allele freq >= alt_threshold and ref freq <= ref_threshold --> record alternative allele)
    :param filter_threshold: Minimum number of reads to pass alternative variants 
                             (ie. filter = PASS if variant depth >= alt_threshold)
    :param maxdepth: Maximum read depth. Default is 1000000
    :param truncate: If truncate is True and a region is given, only pileup columns
                     in the exact region specificied are returned. Default is False
    :param ignoreorphans: Ignore orphans (paired reads that are not in a proper pair). Default is True'
    :param ignore: Keep the most abundant family and ignore families at other positions within each group. Default is False
    :param stepper: Controls how the iterator advances. Accepeted values:
                    'all': skip reads with following flags: BAM_FUNMAP, BAM_FSECONDARY, BAM_FQCFAIL, BAM_FDUP
                    'nofilter': uses every single read turning off any filtering
    :param merge: Merge data, json and consensus files respectively into a 1 single file. Default is True
    :param plot: Generate figure plots if True
    :param report: Generate analysis report if True
    :param call: Convert consensus files to VCF if True
    :param mincov: Minimum read depth to label regions
    :param minratio: Minimum ratio to label regions    
    :param minumis: Minimum number of umis to label regions
    :param minchildren: Minimum number of umi children to label regions
    :param extension: Figure file extension
    :param sample: Sample name to appear in report. If empty str, outdir basename is used
    :param queue: SGE queue for submitting jobs. Default is default
    :param mem: Requested memory for submiiting jobs to SGE. Default is 10g
    :param mypython: Path to python. Default is: /.mounts/labs/PDE/Modules/sw/python/Python-3.6.4/bin/python3.6
    :param mydebarcer: Path to the file debarcer.py. Default is /.mounts/labs/PDE/Modules/sw/python/Python-3.6.4/lib/python3.6/site-packages/debarcer/debarcer.py
       
    Submits jobs to run Umi Grouping, Collapsing and Plotting and Reporting if activated
    '''

    print('run', 'ignoreorphans', args.ignoreorphans, type(args.ignoreorphans))
    print('run', 'ignore', args.ignore, type(args.ignore))
    print('run', 'merge', args.merge, type(args.merge))
    print('run', 'plot', args.plot, type(args.plot))
    print('run', 'report', args.report, type(args.report))


    # get bam file from config or command
    bamfile = GetInputFiles(args.config, args.bamfile, 'bam_file')
    
    # get reference
    reference = GetInputFiles(args.config, args.reference, 'reference_file')
       
    # get output directory from the config or command. set to current dir if not provided
    outdir = GetOutputDir(args.config, args.outdir)
    # create outputdir if doesn't exist
    if os.path.isdir(outdir) == False:
        if os.path.isfile(outdir) == True:
            raise ValueError('ERR: Output directory cannot be a file')
        else:
            os.makedirs(outdir)
    
    # create subdirectoy structure
    CreateDirTree(outdir)

    # get comma-separated list of minimum family size
    famsize = GetFamSize(args.config, args.famsize)
    
    # get thresholds from command or config
    count_threshold = GetThresholds(args.config, 'count_consensus_threshold', args.countthreshold)
    consensus_threshold = GetThresholds(args.config, 'percent_consensus_threshold', args.percentthreshold)
    dist_threshold = GetThresholds(args.config, 'umi_edit_distance_threshold', args.distthreshold)
    post_threshold = GetThresholds(args.config, 'umi_family_pos_threshold', args.postthreshold)
    ref_threshold = GetThresholds(args.config, 'percent_ref_threshold', args.refthreshold)
    alt_threshold = GetThresholds(args.config, 'percent_alt_threshold', args.altthreshold)
    filter_threshold = GetThresholds(args.config, 'filter_threshold', args.filterthreshold)
    
    # create shell scripts and run qsubs to Group and Collapse umis 
    submit_jobs(bamfile, outdir, reference, famsize, args.bedfile, count_threshold,
                consensus_threshold, dist_threshold, post_threshold, ref_threshold,
                alt_threshold, filter_threshold, args.maxdepth, args.truncate, args.ignoreorphans,
                args.ignore, args.merge, args.plot, args.report, args.call, args.mincov,
                args.minratio, args.minumis, args.minchildren, args.extension,
                args.sample, args.mydebarcer, args.mypython, args.mem, args.queue)
    
    
def generate_plots(args):
    '''
    (list) -> None
    
    :param directory: Directory with subdirectories ConsFiles and Datafiles 
    :param config: Path to the config file
    :param extension: Figure format. Accepted values: png, pdf, jpeg, tiff
    :param report: Boolean, generate a report if True
    :param sample: Optional parameter, sample name to appear in report
    :param mincov: Minimum read depth to label regions
    :param minratio: Minimum ratio to label regions    
    :param minumis: Minimum number of umis to label regions
    :param minchildren: Minimum number of umi children to label regions
    :param ref_threshold: Cut Y axis at 100 - ref_threshold
        
    Generate plots in Figures directory
    '''
    
    
    # get the reference threshold to consider variable positions
    # cut Y axis at non-ref-freq
    ref_threshold = GetThresholds(args.config, 'percent_ref_threshold', args.refthreshold)
    non_ref_freq = 100 - ref_threshold
        
    print('plot:', args.report, type(args.report))
    print('plot', 'bool', isinstance(args.report, bool), 'str', isinstance(args.report, str))
    
    # get subdirectories
    L = ['Consfiles', 'Umifiles', 'Stats', 'Datafiles']
    T = [os.path.join(args.directory, i) for i in L]
    for i in T:
        if os.path.isdir(i) == False:
            raise ValueError('ERR: Expecting directory {0}'.format(i))
      
    # unpack directories
    ConsDir, UmiDir, StatsDir, DataDir =  T 
        
    # create directory to save figures if it doesn't exist
    FigDir = os.path.join(args.directory, 'Figures')
    if os.path.isdir(FigDir) == False:
        os.mkdir(FigDir)
        
    # make a list of consensus files that are not empty
    ConsFiles = [os.path.join(ConsDir, i) for i in os.listdir(ConsDir) if i.startswith('chr') and i[-5:] == '.cons']
    # remove empty files in place and print a warning
    DropEmptyFiles(ConsFiles)
    # make a list of datafiles with umis that are not empty
    DataFiles = [os.path.join(DataDir, i) for i in os.listdir(DataDir) if i.startswith('datafile') and 'chr' in i and i[-4:] == '.csv']
    # remove empty files in place and print a warning
    DropEmptyFiles(DataFiles)
    # make a list of umi files
    UmiFiles = [os.path.join(UmiDir, i) for i in os.listdir(UmiDir) if i.startswith('chr') and i[-5:] == '.json']
    # make a list of files with individual umi information
    UmiInfoFiles = [os.path.join(StatsDir, i) for i in os.listdir(StatsDir) if i.startswith('Umis_') and i[-5:] == '.json' and 'before_grouping' in i]
    # make a list of json files with mapping reads information
    MappingInfo = [os.path.join(StatsDir, i) for i in os.listdir(StatsDir) if i.startswith('Mapped') and i[-5:] == '.json']

    # get the file with coverage stats
    CovStats = os.path.join(StatsDir, 'CoverageStats.yml')
    
    # check that paths to files are valid. raise ValueError if file invalid
    CheckFilePath(ConsFiles + DataFiles + UmiFiles + UmiInfoFiles)
    
    # make a list of colors. each color is used for plotting data for a given family size
    Colors = ['black', '#4B0082', '#7B68EE', '#c3baf7', '#8A2BE2',
              '#b54dff', '#BA55D3', '#ce85e0', '#DDA0DD', '#f8ecf8',
              '#066024', '#0ba83f', '#0ff05a', '#57f48c', '#9ff9bd',
              '#b35900', '#e67300', '#ff8c1a', '#ffa64d', '#ffbf80',
              '#b30000', '#e60000', '#ff1a1a', '#ff4d4d', '#ff8080']
    
    # plot proportions of correct and incorrect reads seen during pre-processing
    Inputfile = os.path.join(StatsDir, 'Processing_Read_Info.json')
    CheckFilePath([Inputfile])
    Outputfile = os.path.join(FigDir, 'Proportion_correct_reads.' + args.extension)
    
    print('PlotIncorrectReads')
        
    PlotIncorrectReads(Inputfile, Outputfile, 'preprocessing')
        
    height, width, channels = scipy.ndimage.imread(Outputfile).shape
    print(height, width)
    
    
    
    # plot UMI occurence resulting from pre-processing
    Inputfile = os.path.join(StatsDir, 'Umi_counts.txt')
    CheckFilePath([Inputfile])
    # get umi occurence
    umi_occurence = GetUmiCountFromPreprocessing(Inputfile)
    Outputfile = os.path.join(FigDir, 'UMI_occurence_preprocessing.' + args.extension)
    
    # clear previous ax instances between plots
    # current matplotlib version reuses the earlier instance
    # in future version, a new instance will always be created and returned
    plt.clf(), plt.cla()
    
    print('PlotUMiFrequency')
    
    PlotUMiFrequency(umi_occurence, Outputfile, 'UMI distribution after pre-processing', False)
    
    height, width, channels = scipy.ndimage.imread(Outputfile).shape
    print(height, width)
    

    
    # plot coverage
    plt.clf(), plt.cla()
    
    print('PlotCoverage')
    
    PlotDataPerRegion(CovStats, DataFiles, outputfile=os.path.join(FigDir, 'Coverage_Umi_Count'), mincov=args.mincov, datatype='coverage')

    # plot graphs for each consensus file
    for filename in ConsFiles:
        
        print('PlotMeanFamSize')
        
        # plot mean family size for each consensus file/region
        region = FormatRegion(filename).replace(':', '-')
        Outputfile = os.path.join(FigDir, 'MeanFamilySize_{0}.{1}'.format(region, args.extension))
        plt.clf(), plt.cla()
        PlotMeanFamSize(filename, Colors[1:], Outputfile)
            
        print('PlotNonRefFreqData')
        
        
        
        # plot non-reference frequency
        Outputfile = os.path.join(FigDir, 'NonRefFreq_{0}.{1}'.format(region, args.extension))
        plt.clf(), plt.cla()
        PlotNonRefFreqData(filename, Colors, Outputfile, ylabel='Non-reference allele frequency')
        height, width, channels = scipy.ndimage.imread(Outputfile).shape
        print(height, width)
    
    
        print('PlotNonRefFreqData LOW')
    
    
        # plot non-reference frequency limiting Y axis to 20% for visualization of low-frequency variants 
        Outputfile = os.path.join(FigDir, 'NonRefFreq_low_freq_{0}.{1}'.format(region, args.extension))
        plt.clf(), plt.cla()
        PlotNonRefFreqData(filename, Colors, Outputfile, YLimit=non_ref_freq, title='Y axis cut at {0}%'.format(non_ref_freq), legend='legend')
        
        height, width, channels = scipy.ndimage.imread(Outputfile).shape
        print(height, width)
        
        print('PlotConsDepth')
        
        
        
        # plot raw and consensus depth
        Outputfile = os.path.join(FigDir, 'RawConsensusDepth_{0}.{1}'.format(region, args.extension))    
        #plt.clf(), plt.cla()
        PlotConsDepth(filename, Colors, Outputfile)
       
        height, width, channels = scipy.ndimage.imread(Outputfile).shape
        print(height, width)
    
        
        
    # plot network and network degree for each umi file/region
    for filename in UmiFiles:
        # get region from file name
        region = os.path.basename(filename)
        region = region[:-5]
        region = '-'.join(list(map(lambda x: x.strip(), region.split(':'))))
        
        
        print('PlotNetworkDegree')
        
        
        # plot network and degree
        plt.clf(), plt.cla()
        Outputfile = os.path.join(FigDir, 'UMI_network_degree_{0}.{1}'.format(region, args.extension))        
        PlotNetworkDegree(filename, Outputfile)
        
        height, width, channels = scipy.ndimage.imread(Outputfile).shape
        print(height, width)
    
        
        print('PlotFamSizeReadDepth')
        
        
        # plot marginal distributions of UMI family size and read depth
        plt.clf(), plt.cla()
        Outputfile = os.path.join(FigDir, 'UMI_size_depth_marginal_distribution_{0}.{1}'.format(region, args.extension))
        PlotFamSizeReadDepth(filename, Outputfile)
        
        height, width, channels = scipy.ndimage.imread(Outputfile).shape
        print(height, width)
        
        print('PlotReadDepth')
        
        
        # plot distribution of read depth for each umi families
        plt.clf(), plt.cla()
        Outputfile = os.path.join(FigDir, 'Read_depth_per_umi_family_{0}.{1}'.format(region, args.extension))
        PlotReadDepth(filename, Outputfile)

        height, width, channels = scipy.ndimage.imread(Outputfile).shape
        print(height, width)


    # plot umi frequency for individual umis before grouping
    for filename in UmiInfoFiles:
        
        print('PlotUMiFrequency')
        
        region = os.path.basename(filename)
        region = region[region.index('chr'): region.index('_before')].replace(':', '-')
        # get parent+children and parent only counts
        all_umis, parent_umis = GetIndividualUmiInfo(filename)
        Outputfile = os.path.join(FigDir, 'UMI_freq_distribution_{0}.{1}'.format(region, args.extension)) 
        plt.clf(), plt.cla()
        
        
        
        
        PlotUMiFrequency([all_umis, parent_umis], Outputfile, 'UMI distribution before grouping', True)
    
        height, width, channels = scipy.ndimage.imread(Outputfile).shape
        print(height, width)
    
    # plot proportion of mapped/unmapped reads
    for filename in MappingInfo:
        region = os.path.basename(filename)
        region = region[region.rindex('_')+1:-5].replace(':', '-')
        Outputfile = os.path.join(FigDir, 'Proportion_unmapped_reads_{0}.{1}'.format(region, args.extension))
        plt.clf(), plt.cla()
        
        print('PlotIncorrectReads', 'mapping')
        PlotIncorrectReads(filename, Outputfile, 'mapping')
    
        height, width, channels = scipy.ndimage.imread(Outputfile).shape
        print(height, width)
    

    print('PlotUmiCounts')
    
    # plot children to parent umi count ratio
    plt.clf(), plt.cla()
    Outputfile = os.path.join(FigDir, 'Child_Parent_Umis_Ratio')
    PlotDataPerRegion(CovStats, DataFiles, outputfile=Outputfile, minval=args.minratio, datatype='ratio')

    height, width, channels = scipy.ndimage.imread(Outputfile).shape
    print(height, width)
    
    print('PlotUmiCounts')
    
    
    # plot total umi counts
    plt.clf(), plt.cla()
    PlotDataPerRegion(CovStats, DataFiles, outputfile=os.path.join(FigDir, 'Total_Umis'), minval=args.minumis, datatype='umis')

    
    print('PlotUmiCounts')
    
    
    # plot children umi counts
    plt.clf(), plt.cla()
    PlotDataPerRegion(CovStats, DataFiles, outputfile=os.path.join(FigDir, 'Children_Umis'), minval=args.minchildren, datatype='children')

    
    
    print('PlotParentsToChildrenCounts')
    
    
    # plot children vs parent umis for each interval
    plt.clf(), plt.cla()
    PlotParentsToChildrenCounts(DataFiles, os.path.join(FigDir, 'PTU_vs_CTU.' + args.extension))


    print('PlotParentFreq')



    # plot parent frequencies vs children UMI counts
    plt.clf(), plt.cla()
    PlotParentFreq(DataFiles, Colors, os.path.join(FigDir, 'Children_vs_ParentFreq.' + args.extension))
    
    # check if reporting
    if args.report == True:
        
        if args.extension != 'pdf':
        
            print('make report')

            # create subdirectory
            ReportDir = os.path.join(args.directory, 'Report')
            if os.path.isdir(ReportDir) == False:
                os.mkdir(ReportDir)
            report = os.path.join(ReportDir, 'debarcer_report.html')
            WriteReport(args.directory, args.extension, report, args.mincov, args.minratio, args.minumis, args.minchildren, renderer=mistune.Markdown(), sample=args.sample)
            

def generate_report(args):
    '''
    (list) -> None
    
    :param directory: Directory with subfolders including Figures 
    :param extension: Extension of the figure files
    :param Outputfile: Name of the html report
    :param Options: Optional parameters. Accepted values: 'sample'
    
    Write an html report of debarcer analysis for a given sample
    '''
    
    # create subdirectory
    ReportDir = os.path.join(args.directory, 'Report')
    if os.path.isdir(ReportDir) == False:
        os.mkdir(ReportDir)
    report = os.path.join(ReportDir, 'debarcer_report.html')
    
    # check that subdirectories with required files exist
    T = [os.path.join(args.directory, i) for i in ['Stats', 'Datafiles', 'Figures']]
    for i in T:
        if os.path.isdir(i) == False:
            raise ValueError('ERR: Expecting directory {0}'.format(i))
    
    WriteReport(args.directory, args.extension, report, args.mincov, args.minratio, args.minumis, args.minchildren, renderer=mistune.Markdown(), sample=args.sample)
    

       
if __name__ == '__main__':
        
    ## Argument + config parsing and error handling
    parser = argparse.ArgumentParser(prog='debarcer.py', description="A package for De-Barcoding\
                                     and Error Correction of sequencing data containing molecular barcodes")
    subparsers = parser.add_subparsers()
       		
    ## Preprocess command
    p_parser = subparsers.add_parser('preprocess', help="Preprocess mode for processing fastq files")
    p_parser.add_argument('-o', '--OutDir', dest='outdir', help='Output directory. Available from command or config')
    p_parser.add_argument('-r1', '--Read1', dest='read1', help='Path to first FASTQ file.', required=True)
    p_parser.add_argument('-r2', '--Read2', dest='read2', help='Path to second FASTQ file, if applicable')
    p_parser.add_argument('-r3', '--Read3', dest='read3', help='Path to third FASTQ file, if applicable')
    p_parser.add_argument('-p', '--Prepname', dest='prepname', choices=['HALOPLEX', 'SURESELECT', 'EPIC-DS', 'SIMSENSEQ-PE', 'SIMSENSEQ-SE'], 
                          help='Name of library prep to  use (defined in library_prep_types.ini)', required=True)
    p_parser.add_argument('-pf', '--Prepfile', dest='prepfile', help='Path to your library_prep_types.ini file')
    p_parser.add_argument('-c', '--Config', dest='config', help='Path to your config file')
    p_parser.add_argument('-px', '--Prefix', dest= 'prefix', help='Prefix for naming umi-reheradered fastqs. Use Prefix from Read1 if not provided') 
    p_parser.set_defaults(func=preprocess_reads)
    
    ## UMI group command
    g_parser = subparsers.add_parser('group', help="Groups UMIs into families.")
    g_parser.add_argument('-o', '--Outdir', dest='outdir', help='Output directory where subdirectories are created')
    g_parser.add_argument('-r', '--Region', dest='region', help='Region coordinates to search for UMIs. chrN:posA-posB. posA and posB are 1-based included', required=True)
    g_parser.add_argument('-b', '--Bamfile', dest='bamfile', help='Path to the BAM file')
    g_parser.add_argument('-c', '--Config', dest='config', help='Path to the config file')
    g_parser.add_argument('-d', '--Distance', dest='distthreshold', type=int, help='Hamming distance threshold for connecting parent-children umis')
    g_parser.add_argument('-p', '--Position', dest='postthreshold', type=int, help='Umi position threshold for grouping umis together')
    g_parser.add_argument('-i', '--Ignore', dest='ignore', choices=[True, False], type=ConvertArgToBool, default=False, help='Keep the most abundant family and ignore families at other positions within each group. Default is False')
    g_parser.add_argument('-t', '--Truncate', dest='truncate', choices=[True, False], default=False, type=ConvertArgToBool, help='Discard reads overlapping with the genomic region if True. Default is False')
    g_parser.set_defaults(func=group_umis)
    
    ## Base collapse command
    c_parser = subparsers.add_parser('collapse', help="Base collapsing from given UMI families file.")
    c_parser.add_argument('-c', '--Config', dest='config', help='Path to the config file')
    c_parser.add_argument('-o', '--Outdir', dest='outdir', help='Output directory where subdirectories are created')
    c_parser.add_argument('-b', '--Bamfile', dest='bamfile', help='Path to the BAM file')
    c_parser.add_argument('-rf', '--Reference', dest='reference', help='Path to the refeence genome')
    c_parser.add_argument('-r', '--Region', dest='region', help='Region coordinates to search for UMIs. chrN:posA-posB. posA and posB are 1-based included', required=True)
    c_parser.add_argument('-u', '--Umi', dest='umifile', help='Path to the .umis file', required=True)
    c_parser.add_argument('-f', '--Famsize', dest='famsize', help='Comma-separated list of minimum umi family size to collapase on')
    c_parser.add_argument('-ct', '--CountThreshold', dest='countthreshold', type=int, help='Base count threshold in pileup column')
    c_parser.add_argument('-pt', '--PercentThreshold', dest='percentthreshold', type=float, help='Majority rule consensus threshold in pileup column')
    c_parser.add_argument('-p', '--Position', dest='postthreshold', type=int, help='Umi position threshold for grouping umis together')
    c_parser.add_argument('-m', '--MaxDepth', dest='maxdepth', default=1000000, type=int, help='Maximum read depth. Default is 1000000')
    c_parser.add_argument('-t', '--Truncate', dest='truncate', choices=[True, False], default=False, type=ConvertArgToBool, help='If truncate is True and a region is given,\
                          only pileup columns in the exact region specificied are returned. Default is False')
    c_parser.add_argument('-i', '--IgnoreOrphans', dest='ignoreorphans', choices=[True, False], default=False, type=ConvertArgToBool, help='Ignore orphans (paired reads that are not in a proper pair). Default is False')
    c_parser.add_argument('-stp', '--Stepper', dest='stepper', choices=['all', 'nofilter'], default='nofilter',
                          help='Filter or include reads in the pileup. Options all: skip reads with BAM_FUNMAP, BAM_FSECONDARY, BAM_FQCFAIL, BAM_FDUP flags,\
                          nofilter: uses every single read turning off any filtering')
    c_parser.set_defaults(func=collapse)

    ## Variant call command - requires cons file (can only run after collapse)
    v_parser = subparsers.add_parser('call', help="Convert consensus file into VCF format.")
    v_parser.add_argument('-o', '--Outdir', dest='outdir', help='Output directory where subdirectories are created')
    v_parser.add_argument('-c', '--Config', dest='config', help='Path to the config file')
    v_parser.add_argument('-rf', '--Reference', dest='reference', help='Path to the refeence genome')
    v_parser.add_argument('-f', '--Famsize', dest='famsize', help='Comma-separated list of minimum umi family size to collapase on')
    v_parser.add_argument('-rt', '--RefThreshold', dest='refthreshold', default=95, type=float, 
                          help='Maximum reference frequency to consider (%) alternative variants\
                          (ie. position with ref freq <= ref_threshold is considered variable)')
    v_parser.add_argument('-at', '--AlternativeThreshold', dest='altthreshold', type=float, default=2,
                          help='Minimum allele frequency (%) to consider an alternative allele at a variable position\
                          (ie. allele freq >= alt_threshold and ref freq <= ref_threshold: alternative allele)')
    v_parser.add_argument('-ft', '--FilterThreshold', dest='filterthreshold', type=int, default=10,
                          help='Minimum number of reads to pass alternative variants\
                          (ie. filter = PASS if variant depth >= alt_threshold)Filter threshold')
    v_parser.set_defaults(func=VCF_converter)
    
    ## Run scripts command 
    r_parser = subparsers.add_parser('run', help="Generate scripts for umi grouping, collapsing and VCF formatting for target regions specified by the BED file.")
    r_parser.add_argument('-o', '--Outdir', dest='outdir', help='Output directory where subdirectories are created')
    r_parser.add_argument('-c', '--Config', dest='config', help='Path to the config file')
    r_parser.add_argument('-b', '--Bamfile', dest='bamfile', help='Path to the BAM file')
    r_parser.add_argument('-rf', '--Reference', dest='reference', help='Path to the refeence genome')
    r_parser.add_argument('-f', '--Famsize', dest='famsize', help='Comma-separated list of minimum umi family size to collapase on')
    r_parser.add_argument('-bd', '--Bedfile', dest='bedfile', help='Path to the bed file', required=True)
    r_parser.add_argument('-ct', '--CountThreshold', dest='countthreshold', type=int, help='Base count threshold in pileup column')
    r_parser.add_argument('-pt', '--PercentThreshold', dest='percentthreshold', type=float, help='Base percent threshold in pileup column')
    r_parser.add_argument('-p', '--Position', dest='postthreshold', type=int, help='Umi position threshold for grouping umis together')
    r_parser.add_argument('-d', '--Distance', dest='distthreshold', type=int, help='Hamming distance threshold for connecting parent-children umis')
    r_parser.add_argument('-rt', '--RefThreshold', dest='refthreshold', default=95, type=float, help='A position is considered variable of reference frequency is <= ref_threshold')
    r_parser.add_argument('-at', '--AlternativeThreshold', dest='altthreshold', default=2, type=float, help='Variable position is labeled PASS if allele frequency >= alt_threshold')
    r_parser.add_argument('-ft', '--FilterThreshold', dest='filterthreshold', default=10, type=int, help='Minimum number of reads to pass alternative variants')
    r_parser.add_argument('-m', '--MaxDepth', dest='maxdepth', default=1000000, type=int, help='Maximum read depth. Default is 1000000')
    r_parser.add_argument('-t', '--Truncate', dest='truncate', action='store_true', help='Only pileup columns in the exact region specificied are returned. Default is False, becomes True is used')
    r_parser.add_argument('-io', '--IgnoreOrphans', dest='ignoreorphans', action='store_true', help='Ignore orphans (paired reads that are not in a proper pair). Default is False, becomes True if used')
    r_parser.add_argument('-i', '--Ignore', dest='ignore', action='store_true', help='Keep the most abundant family and ignore families at other positions within each group. Default is False, becomes True if used')
    r_parser.add_argument('-mg', '--Merge', dest='merge', action='store_false', help='Merge data, json and consensus files respectively into a 1 single file. Default is True, becomes False if used')
    r_parser.add_argument('-pl', '--Plot', dest='plot',  action='store_false', help='Generate figure plots. Default is True, becomes False if used')
    r_parser.add_argument('-rp', '--Report', dest='report', action='store_false', help='Generate report. Default is True, becomes False if used')
    r_parser.add_argument('-cl', '--Call', dest='call', action='store_false', help='Convert consensus files to VCF format. Default is True, becomes False if used')
    r_parser.add_argument('-ex', '--Extension', dest='extension', choices=['png', 'jpeg', 'pdf'], default='png', help='Figure format. Does not generate a report if pdf, even with -r True. Default is png')
    r_parser.add_argument('-sp', '--Sample', dest='sample', help='Sample name to appear to report. Optional, use Output directory basename if not provided')
    r_parser.add_argument('-q', '--Queue', dest='queue', default='default', help='SGE queue for submitting jobs. Default is default')
    r_parser.add_argument('-mm', '--Memory', dest='mem', default=20, type=int, help='Requested memory for submitting jobs to SGE. Default is 20g')
    r_parser.add_argument('-py', '--MyPython', dest='mypython', default='/.mounts/labs/PDE/Modules/sw/python/Python-3.6.4/bin/python3.6',
                          help='Path to python. Default is /.mounts/labs/PDE/Modules/sw/python/Python-3.6.4/bin/python3.6')
    r_parser.add_argument('-db', '--MyDebarcer', dest='mydebarcer', default='/.mounts/labs/PDE/Modules/sw/python/Python-3.6.4/lib/python3.6/site-packages/debarcer/debarcer.py',
                          help='Path to the file debarcer.py. Default is /.mounts/labs/PDE/Modules/sw/python/Python-3.6.4/lib/python3.6/site-packages/debarcer/debarcer.py')
    r_parser.add_argument('-mv', '--MinCov', dest='mincov', type=int, default=1000, help='Minimum coverage value. Values below are plotted in red')
    r_parser.add_argument('-mr', '--MinRatio', dest='minratio', type=float, default=0.1, help='Minimum children to parent umi ratio. Values below are plotted in red')
    r_parser.add_argument('-mu', '--MinUmis', dest='minumis', type=int, default=1000, help='Minimum umi count. Values below are plotted in red')
    r_parser.add_argument('-mc', '--MinChildren', dest='minchildren', type=int, default=500, help='Minimum children umi count. Values below are plotted in red')
    r_parser.add_argument('-stp', '--Stepper', dest='stepper', choices=['all', 'nofilter'], default='nofilter',
                          help='Filter or include reads in the pileup. Options all: skip reads with BAM_FUNMAP, BAM_FSECONDARY, BAM_FQCFAIL, BAM_FDUP flags,\
                          nofilter: uses every single read turning off any filtering')
    r_parser.set_defaults(func=run_scripts)
    
    ## Merge files command 
    m_parser = subparsers.add_parser('merge', help="Merge files from each region into a single file")
    m_parser.add_argument('-d', '--Directory', dest='directory', help='Directory containing files to be merged')
    m_parser.add_argument('-dt', '--DataType', dest='datatype', choices=['datafiles', 'consensusfiles', 'umifiles'], help='Type of files to be merged', required=True)
    m_parser.set_defaults(func=merge_files)
    
    ## Generate graphs	
    plot_parser = subparsers.add_parser('plot', help="Generate graphs for umi and cons data files", add_help=True)
    plot_parser.add_argument('-c', '--Config', dest='config', help='Path to the config file')
    plot_parser.add_argument('-d', '--Directory', dest='directory', help='Directory with subdirectories ConsFiles and Datafiles', required=True)
    plot_parser.add_argument('-e', '--Extension', dest='extension', default='png', choices=['pdf', 'png', 'jpeg'], help='Figure format. Does not generate a report if pdf, even with -r True. Default is png')
    plot_parser.add_argument('-s', '--Sample', dest='sample', help='Sample name to apear in the report is reporting flag activated. Optional')
    plot_parser.add_argument('-r', '--Report', dest='report', choices=[False, True], type=ConvertArgToBool, default=True, help='Generate a report if activated. Default is True')
    plot_parser.add_argument('-mv', '--MinCov', dest='mincov', type=int, default=1000, help='Minimum coverage value. Values below are plotted in red')
    plot_parser.add_argument('-mr', '--MinRatio', dest='minratio', type=float, default=0.1, help='Minimum children to parent umi ratio. Values below are plotted in red')
    plot_parser.add_argument('-mu', '--MinUmis', dest='minumis', type=int, default=1000, help='Minimum umi count. Values below are plotted in red')
    plot_parser.add_argument('-mc', '--MinChildren', dest='minchildren', type=int, default=500, help='Minimum children umi count. Values below are plotted in red')
    plot_parser.add_argument('-rt', '--RefThreshold', dest='refthreshold', default=95, type=float, help='Cut Y axis at non-ref frequency, the minimum frequency to consider a position variable')
    plot_parser.set_defaults(func=generate_plots)
    
    ## Generate report
    report_parser = subparsers.add_parser('report', help="Generate report", add_help=True)
    report_parser.add_argument('-d', '--Directory', dest='directory', help='Directory with subdirectories including Figures', required=True)
    report_parser.add_argument('-e', '--Extension', dest='extension', default='png', choices=['pdf', 'png', 'jpeg'], help='Figure format. Does not generate a report if pdf, even with -r True. Default is png')
    report_parser.add_argument('-s', '--Sample', dest='sample', help='Sample name. Optional. Directory basename is sample name if not provided')
    report_parser.add_argument('-mv', '--MinCov', dest='mincov', type=int, default=1000, help='Minimum coverage value. Values below are plotted in red')
    report_parser.add_argument('-mr', '--MinRatio', dest='minratio', type=float, default=0.1, help='Minimum children to parent umi ratio. Values below are plotted in red')
    report_parser.add_argument('-mu', '--MinUmis', dest='minumis', type=int, default=1000, help='Minimum umi count. Values below are plotted in red')
    report_parser.add_argument('-mc', '--MinChildren', dest='minchildren', type=int, default=500, help='Minimum children umi count. Values below are plotted in red')
    report_parser.set_defaults(func=generate_report)
        
    args = parser.parse_args()
    try:
        args.func(args)
    except AttributeError as e:
        print(e)
        print(parser.format_help())
    
