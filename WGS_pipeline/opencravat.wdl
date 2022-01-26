# Given a set of samples, combine segment files into a single file
# more information available at https://open-cravat.readthedocs.io/en/latest/2.-Command-line-usage.html
workflow opencravat {
    call run_opencravat
}

task run_opencravat {
    String sample_id
    File vcf
    String format = "vcf"
    String annotators_to_use = ""
    
    Int memory = 16
    Int boot_disk_size = 20
    Int disk_space
    Int num_threads = 1
    Int num_preempt = 5
    String docker = "karchinlab/opencravat"

    command {
      set -euo pipefail
        
      oc module install-base
      oc module install -y ${annotators_to_use}
      
      # to make it faster we should use a copy from a bucket using gsutil cp
      # we install everything on a machine, then get path to data using `oc config md`
      # we then cp it on a bucket.
      # now we can add two additional commands here:
      # 1. to copy the content of the bucket here: gsutil -m cp -r gs://pathtomd/../* LOCATION
      # 2. to use this location as the md location: oc config md LOCATION
      
      oc run ${vcf} -l hg38 -t ${format} –mp ${num_threads} –version

      mv ${vcf}.err ${sample_id}.variant_annotations.err
      mv ${vcf}.log ${sample_id}.variant_annotations.log
      mv ${vcf}.sqlite ${sample_id}.variant_annotations.sqlite
      mv ${vcf}.tsv ${sample_id}.variant_annotations.tsv

      gzip ${sample_id}.variant_annotations.${format}
    }

    output {
        File oc_error_file="${sample_id}.variant_annotations.err"
        File oc_log_file="${sample_id}.variant_annotations.log"
        File oc_tsv_file="${sample_id}.variant_annotations.${format}.gz"
    }

    runtime {
        docker: docker
        bootDiskSizeGb: "${boot_disk_size}"
        memory: "${memory}GB"
        disks: "local-disk ${disk_space} HDD"
        cpu: "${num_threads}"
        preemptible: "${num_preempt}"
    }

    meta {
        author: "David Wu"
    }
}
