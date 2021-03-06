Debarcer
========

A package for De-Barcoding and Error Correction of sequencing data containing molecular barcodes. For information on getting started, including installing and running ```Debarcer```, see the [wiki](https://github.com/oicr-gsi/debarcer/wiki/)


Note : The repository for the original release of Debarcer (V0.3.1) as described in Nature Protocols can be found under 
https://github.com/oicr-gsi/debarcer/releases/tag/v0.3.1
 
https://github.com/oicr-gsi/debarcer/tree/master-old


# Configuration


A sample config file is provided in ``/debarcer/config/sample_config.ini``, and a sample prepfile is provided in ``/debarcer/config/library_prep_types.ini``.
Parameters provided in the config can also be provided in the command. But parameters in the config have precedence over parameters in the command if duplicated.

The prepfile contains instructions for how different library preps should be handled.
Information for several library preps is already in the prep file. Custom library prep is available but it should be noted that:
- a single UMI is allowed
- UMI length is constant for all reads
- the same spacer sequence is expected for all reads, if present

Example information required in the prepfile:


```python
[SIMSENSEQ-PE]
INPUT_READS=2
OUTPUT_READS=2
UMI_LOCS=1
UMI_LENS=12
SPACER=TRUE
SPACER_SEQ=ATGGGAAAGAGTGTCC
UMI_POS=1
UMI_INLINE=TRUE
```

* INPUT_READS: Number of unprocessed fastq files (1-3)
* OUTPUT_READS: Number of reheadered fastq files (1-2)
* UMI_LOCS: Indices of unprocessed fastq files with a UMI (1-3). Single value or comma-separated
* UMI_LENS: Lengths of the UMIs in each fastq with umis. Single value or comma-separated
* SPACER: True if a spacer is used (TRUE/FALSE)
* SPACER_SEQ: Sequence of the spacer ([A,C,G,T]+)
* UMI_POS: Left-most position of the umi within read (1-based). Single value or comma-separated
* UMI_INLINE: True id umis are inline with reads, False if umis are in separate input fastq (TRUE/FALSE)

Single-value of parameters UMI_LENS, UMI_POS are propagated to all fastqs with umis.
However, for comma-separated values, info must be listed in the same order as UMI_LOCS,
and the number of values must match that of UMI_LOCS

Multiple spacers are not allowed. It is assumed that the same spacer is used for all input fastqs with umis if spacer if present.
Use empty string or None to specify SPACER_SEQ when SPACER=False

```LIBRARY_NAME``` (eg, SIMSENSEQ-PE) would then be the ```--prepname``` argument passed to debarcer.py.


# Typical Workflow
Example commands. See the [wiki](https://github.com/oicr-gsi/debarcer/wiki/) for a full description of parameters


1. Preprocess fastq files
```python
debarcer preprocess -o /path/to/output_dir -r1 /path/to/read1.fastq -r /path/to/read2.fastq
-p "SIMSENSEQ-PE" -pf /path/to/library_prep_types.ini -c /path/to/config.ini -px newfile_name
```

2. Align processed fastqs (outside of debarcer)

   debarcer does not align processed fastqs
   * align fastqs (eg, with bwa-mem)
   * bam should then be coordinate-sorted
   * index bam
   bam_file.bam and bam_file.bam.bai are required for following steps

3. Error-correct and group UMIs into families
```python
debarcer group -o /path/to/output_dir -r "chrN:posA-posB" -b /path/to/bamfile.bam -d 1 -p 10 -i False
-t False
```

4. Perform base collapsing
```python
debarcer collapse -o /path/to/output_dir -b /path/to/bamfile.bam -rf /path/to/reference_genome
-r "chrN:posA-posB" -u /path/to/Umifiles/umifile.json -f "1,3,5" -ct 1 -pt 50 -p 10 -m 1000000 -t False
-i False -stp nofilter
```

5. Call variants for specified umi family size
```python
debarcer call -o /path/to/output_dir -rf /path/to/reference_genome -rt 95 -at 2 -ft 10 -f 3
```

6. Generate plots
```python
debarcer plot -d /path/to/main_directory -e png -s my_sample_name -r True -mv 1000 -mr 0.1 -mu 1000
-mc 500 -rt 95
```

7. Generate report
```python
debarcer report -d /path/to/main_directory -e png -s my_sample_name -mv 1000 -mr 0.1 -mu 1000
-mc 500
```

# Dependencies

Debarcer was tested using Python 3.6.4 and depends on the packages pysam and pandas (among others).
See ```requirements.txt```.
