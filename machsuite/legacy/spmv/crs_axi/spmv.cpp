/*
Based on algorithm described here:
http://www.cs.berkeley.edu/~mhoemmen/matrix-seminar/slides/UCB_sparse_tutorial_1.pdf
*/

#include "spmv.hpp"

// Per-port AXI master interfaces (serial kernel — no shared-bus/OpenMP path)
#pragma HLS interface port = val mode = m_axi offset = direct
#pragma HLS interface port = cols mode = m_axi offset = direct
#pragma HLS interface port = rowDelimiters mode = m_axi offset = direct
#pragma HLS interface port = vec mode = m_axi offset = direct
#pragma HLS interface port = out mode = m_axi offset = direct
void spmv(TYPE* val, int32_t* cols, int32_t* rowDelimiters, TYPE* vec, TYPE* out)
{
   int i, j;
   TYPE sum, Si;

spmv_1:
   for(i = 0; i < N; i++)
   {
      sum = 0;
      Si = 0;
      int tmp_begin = rowDelimiters[i];
      int tmp_end = rowDelimiters[i + 1];
   spmv_2:
      for(j = tmp_begin; j < tmp_end; j++)
      {
         Si = val[j] * vec[cols[j]];
         sum = sum + Si;
      }
      out[i] = sum;
   }
}
