# Given a set of samples, combine segment files into a single file
workflow opencravat {
    call opencravat
}

task opencravat {
    String sample_id
    File vcf
    String annotators_to_use
    
    Int memory
    Int disk_space
    Int num_threads
    Int num_preempt

    command {
      set -euo pipefail
        
      oc module install-base
      oc module install -y ${annotators_to_use}
      oc run ${vcf} -l hg38 -a ${annotators_to_use} -t text 

      mv ${vcf}.err ${sample_id}.variant_annotations.err
      mv ${vcf}.log ${sample_id}.variant_annotations.log
      mv ${vcf}.sqlite ${sample_id}.variant_annotations.sqlite
      mv ${vcf}.tsv ${sample_id}.variant_annotations.tsv

      gzip ${sample_id}.*
    }

    output {
        File oc_error_file="${sample_id}.variant_annotations.err.gz"
        File oc_log_file="${sample_id}.variant_annotations.log.gz"
        File oc_sqlite_file="${sample_id}.variant_annotations.sqlite.gz"
        File oc_tsv_file="${sample_id}.variant_annotations.tsv.gz"
    }

    runtime {
        docker: "karchinlab/opencravat"
        memory: "${memory}GB"
        disks: "local-disk ${disk_space} HDD"
        cpu: "${num_threads}"
        preemptible: "${num_preempt}"
    }

    meta {
        author: "David Wu"
    }
}
