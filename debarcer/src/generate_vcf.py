# -*- coding: utf-8 -*-
"""
Created on Fri Oct 25 14:25:48 2019

@author: RJovelin
"""

import time
from src.version import __version__


def GetConsData(consfile):
    '''
    (str) -> dict
    
    :param consfile: Path to the consensus file (merged or not)
    
    Returns a dictionary with consensus file info organized by chromo, and family
    size for each position
    '''

    # create a dict with consensus info per contig, region and umi family size
    # {contig :{fam: {pos: info}}}
    data = {}

    infile = open(consfile)
    header = infile.readline().rstrip().split('\t')
    
    for line in infile:
        line = line.rstrip()
        if line != '':
            line = line.split('\t')
            contig = line[header.index('CHROM')]
            if contig not in data:
                data[contig] = {}
            # get the position
            pos = int(line[header.index('POS')])
            # get umi fam size              
            famsize = int(line[header.index('FAM')])
            if famsize not in data[contig]:
                data[contig][famsize] = {}
            # collect info     
            assert pos not in data[contig][famsize]
            data[contig][famsize][pos] = line
    
    infile.close()
    return data
        
    

def WriteVCF(consfile, outputfile, reference, famsize, ref_threshold, alt_threshold, filter_threshold):
    '''
    (str, str, str, int, float, int, int) -> None
    
    :param consfile: Path to the consensus file (merged or not)
    :param outputfile: Path to the output VCF file
    :param reference" Path to the reference genome 
    :param famsize: Minimum umi family size to collapse umi
    :param ref_threshold: Maximum reference frequency (in %) to consider alternative variants
                          (ie. position with ref freq <= ref_threshold is considered variable)
    :param alt_threshold: Minimum allele frequency (in %) to consider an alternative allele at a variable position 
                          (ie. allele freq >= alt_threshold and ref freq <= ref_threshold --> record alternative allele)
    :param filter_threshold: minimum number of reads to pass alternative variants 
                             (ie. filter = PASS if variant depth >= alt_threshold)
      
    Write a VCF from the consensus file. Allow multiple records per position for each family sizes.
    '''
    
    # parse consensus file
    consdata = GetConsData(consfile)

    # get the header of the consfile
    infile = open(consfile)
    header = infile.readline().rstrip().split('\t')
    infile.close()

    # get debarcer version
    version = __version__

    # open file for writing
    newfile = open(outputfile, 'w')

    # write VCF header 
    newfile.write('##fileformat=VCFv4.1\n')
    newfile.write('##fileDate={0}\n'.format(time.strftime('%Y%m%d', time.localtime())))
    newfile.write('##reference={0}\n'.format(reference))
    newfile.write('##source=Debarcer v. {0}\n'.format(version))
    newfile.write('##f_size={0}\n'.format(famsize))
        
    # write info/filter/format metadata
    newfile.write('##INFO=<ID=RDP,Number=1,Type=Integer,Description=\"Raw Depth\">\n')
    newfile.write('##INFO=<ID=CDP,Number=1,Type=Integer,Description=\"Consensus Depth\">\n')
    newfile.write('##INFO=<ID=MIF,Number=1,Type=Integer,Description=\"Minimum Family Size\">\n')
    newfile.write('##INFO=<ID=MNF,Number=1,Type=Float,Description=\"Mean Family Size\">\n')
    newfile.write('##INFO=<ID=AD,Number=1,Type=Integer,Description=\"Reference allele Depth\">\n')
    newfile.write('##INFO=<ID=AL,Number=A,Type=Integer,Description=\"Alternate Allele Depth\">\n')
    newfile.write('##INFO=<ID=AF,Number=A,Type=Float,Description=\"Alternate Allele Frequency\">\n')
    newfile.write('##FILTER=<ID=a{0},Description=\"Alternate allele depth below {0}\">\n'.format(filter_threshold))
        
    # write data header 
    newfile.write('\t'.join(['#CHROM', 'POS', 'ID', 'REF', 'ALT', 'QUAL', 'FILTER', 'INFO']) + '\n')

    # loop over sorted contigs and sorted positions in cons data for given famsize 
    
    # make a sorted list of contigs
    Chromosomes = [i.replace('chr', '') for i in consdata.keys()]
    # make a list of non numerical contigs
    others = sorted([Chromosomes.pop(i) for i in range(len(Chromosomes)) if Chromosomes[i].isnumeric() == False])
    Chromosomes = sorted(list(map(lambda x: int(x), Chromosomes)))
    Chromosomes = list(map(lambda x: 'chr' + str(x), Chromosomes))
    # add back non-numerical contigs
    Chromosomes.extend(others)
    
    # make a list of family sizes
    famsize = []
    for i in consdata:
        famsize.extend(list(consdata[i].keys()))
    famsize = sorted(list(map(lambda x: int(x), list(set(famsize)))))
        
    for contig in Chromosomes:
        for size in famsize:
            for pos in sorted(consdata[contig][size]):
                L = consdata[contig][size][pos]
                # get reference frequency
                ref_freq = float(L[header.index('REF_FREQ')]) 
                # create VCF record if ref freq low enough to consider variant at position 
                if ref_freq <= ref_threshold:
                    # get consensus and raw depth       
                    consdepth = int(L[header.index('CONSDP')])
                    rawdepth = int(L[header.index('RAWDP')])
                    # get minimum and mean family size
                    minfam = int(L[header.index('FAM')])
                    meanfam = float(L[header.index('MEAN_FAM')])
                    # set up info
                    info = 'RDP={0};CDP={1};MIF={2};MNF={3};AD={4};AL={5};AF={6}'
        
                    # get the reference allele
                    ref = L[header.index('REF')]
                    # get the list of alleles
                    alleles = ['A', 'C', 'G', 'T', 'I', 'D', 'N']
                    # get the allele read depth
                    depth = {i:int(L[header.index(i)]) for i in alleles}
                    # compute allele frequency for each allele
                    freq = {i: (depth[i]/sum(depth.values())) * 100 for i in alleles}
                
                    # make a list of alternative alleles with frequency >= alt_threshold
                    alt_alleles = [i for i in freq if i != ref and freq[i] >= alt_threshold]
                    # make a list of read depth for alternative alleles passing alt_threshold
                    alt_depth = [str(depth[i]) for i in alt_alleles]
                    # make a list of frequencies for alternative alelles passing alt_threshold 
                    alt_freq = [str(round(freq[i], 4)) for i in alt_alleles]
                    # record info
                    info = info.format(rawdepth, consdepth, minfam, round(meanfam, 2), depth[ref], ','.join(alt_depth), ','.join(alt_freq))
                                   
                    # get the filter value based on min_read_depth
                    if True in [depth[i] >= filter_threshold for i in alt_alleles]:
                        filt = 'PASS' 
                    else:
                        filt = 'a{0}'.format(filter_threshold)
            
                    newfile.write('\t'.join([contig, str(pos), '.', ref, ','.join(alt_alleles), '0', filt, info]) + '\n')
            
    newfile.close()        

