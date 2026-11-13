/*
Implementation based on:
Hong, Oguntebi, Olukotun. "Efficient Parallel Graph Exploration on Multi-Core CPU and GPU." PACT, 2011.
*/

#include "bfs.hpp"

#define Q_PEEK(x) (iter % 2 == 0 ? queue1[x] : queue2[x])

#ifndef THREAD_NUMBER
#define THREAD_NUMBER 1
#endif

#define ALLOCATION_SIZE 16

// AXI bus mode: all params on shared AXI bus (required for OpenMP compatibility)
#pragma HLS bus mode = m_axi
#pragma HLS interface port = nodes mode = bus
#pragma HLS interface port = edges mode = bus
#pragma HLS interface port = level mode = bus
#pragma HLS interface port = level_counts mode = bus
void bfs(node_t* nodes, edge_t* edges, node_index_t starting_node, level_t* level, edge_index_t* level_counts)
{
   node_index_t queue1[N_NODES + ALLOCATION_SIZE * THREAD_NUMBER];
   node_index_t queue2[N_NODES + ALLOCATION_SIZE * THREAD_NUMBER];
   node_index_t q_n1, q_n2;
   node_index_t iter;

   for(unsigned i = 0; i < N_LEVELS; i++)
   {
      level_counts[i] = 0;
   }

#pragma omp parallel num_threads(THREAD_NUMBER)
   {
#pragma omp for
      for(node_index_t n = 0; n < N_NODES; n++)
      {
         level[n] = MAX_LEVEL;
      }
   }

   queue1[0] = starting_node;
   q_n1 = 1;
   q_n2 = 0;
   level[starting_node] = 0;
   iter = 0;

   node_index_t q_n = q_n1;
   while(q_n != 0)
   {
      unsigned allocated = ALLOCATION_SIZE;
      unsigned position = 0;
#pragma omp parallel firstprivate(position, allocated) num_threads(THREAD_NUMBER)
      {
#pragma omp for
         for(unsigned i = 0; i < q_n; i++)
         {
            node_index_t n = Q_PEEK(i);
            if(n < (N_NODES + 1))
            {
               edge_index_t tmp_begin = nodes[n].edge_begin;
               edge_index_t tmp_end = nodes[n].edge_end;
               for(edge_index_t e = tmp_begin; e < tmp_end; e++)
               {
                  node_index_t tmp_dst = edges[e].dst;
                  level_t tmp_level = level[tmp_dst];

                  if(tmp_level == MAX_LEVEL)
                  {
                     level[tmp_dst] = iter + 1;
                     if(iter % 2 == 0)
                     {
                        if(allocated == ALLOCATION_SIZE)
                        {
#pragma omp critical
                           {
                              position = q_n2;
                              q_n2 += ALLOCATION_SIZE;
                           }
                           allocated = 0;
                        }
                        queue2[position + allocated] = tmp_dst;
                        allocated++;
                     }
                     else
                     {
                        if(allocated == ALLOCATION_SIZE)
                        {
#pragma omp critical
                           {
                              position = q_n1;
                              q_n1 += ALLOCATION_SIZE;
                           }
                           allocated = 0;
                        }
                        queue1[position + allocated] = tmp_dst;
                        allocated++;
                     }
                  }
               }
            }
         }

         while(allocated < ALLOCATION_SIZE)
         {
            if(iter % 2 == 0)
            {
               queue2[position + allocated] = N_NODES + 1;
            }
            else
            {
               queue1[position + allocated] = N_NODES + 1;
            }
            allocated++;
         }
      }
      iter++;
      q_n = (iter % 2 == 0) ? q_n1 : q_n2;
      q_n1 = 0;
      q_n2 = 0;
   }

#pragma omp parallel num_threads(THREAD_NUMBER)
   {
      edge_index_t level0 = 0;
      edge_index_t level1 = 0;
      edge_index_t level2 = 0;
      edge_index_t level3 = 0;
      edge_index_t level4 = 0;
      edge_index_t level5 = 0;
      edge_index_t level6 = 0;

#pragma omp for
      for(int i = 0; i < N_NODES; ++i)
      {
         if(level[i] == 0)
         {
            level0++;
         }
         else if(level[i] == 1)
         {
            level1++;
         }
         else if(level[i] == 2)
         {
            level2++;
         }
         else if(level[i] == 3)
         {
            level3++;
         }
         else if(level[i] == 4)
         {
            level4++;
         }
         else if(level[i] == 5)
         {
            level5++;
         }
         else if(level[i] == 6)
         {
            level6++;
         }
      }

#pragma omp critical
      {
         level_counts[0] += level0;
         level_counts[1] += level1;
         level_counts[2] += level2;
         level_counts[3] += level3;
         level_counts[4] += level4;
         level_counts[5] += level5;
         level_counts[6] += level6;
      }
   }
}
